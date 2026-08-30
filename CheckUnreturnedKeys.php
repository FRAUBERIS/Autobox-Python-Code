<?php

namespace App\Console\Commands;

use App\Models\Key;
use App\Models\User;
use App\Models\Schedule;
use App\Models\Transaction;
use App\Models\AccessLog;
use App\Http\Controllers\Api\AuthQrController;
use App\Events\KeyStatusUpdated;
use App\Events\AccessLogged;
use App\Mail\KeyUnreturnedUserNotice;
use App\Mail\KeyUnreturnedAdminAlert;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Mail;
use Illuminate\Support\Facades\Log;

class CheckUnreturnedKeys extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'autobox:check-unreturned {--force : Force sending email ignoring cooldown}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Trigger emails ONLY when a borrowed key has not been returned and the schedule is expired (e.g. past end time like 8:00 -> 8:01).';

    /**
     * Execute the console command.
     */
    public function handle()
    {
        $this->info("Checking for borrowed keys with EXPIRED schedules...");

        // 1. Find all active unreturned borrow transactions
        $unreturnedBorrows = Transaction::where('action', 'borrow')
            ->whereNull('returned_at')
            ->with(['user', 'key'])
            ->get();

        if ($unreturnedBorrows->isEmpty()) {
            $this->info("All keys are accounted for. No unreturned keys.");
            return Command::SUCCESS;
        }

        $today = strtolower(now()->format('l'));
        $currentTime = now()->format('H:i:s');
        $admins = User::where('role', 'admin')->whereNotNull('email')->get();
        $expiredCount = 0;

        foreach ($unreturnedBorrows as $tx) {
            $borrower = $tx->user;
            $key = $tx->key;

            if (!$key) {
                continue;
            }

            if (!$borrower) {
                $borrower = AuthQrController::resolveLastBorrower($key);
            }

            if (!$borrower) {
                continue;
            }

            // 2. Find schedule for this user and key (latest active schedule)
            $schedule = Schedule::where('user_id', $borrower->id)
                ->where('key_id', $key->id)
                ->where('day_of_week', $today)
                ->where('is_active', true)
                ->latest()
                ->first();

            // Fallback: check any active schedule for this user & key
            if (!$schedule) {
                $schedule = Schedule::where('user_id', $borrower->id)
                    ->where('key_id', $key->id)
                    ->where('is_active', true)
                    ->latest()
                    ->first();
            }

            $isExpired = false;
            $expiredReason = '';

            if ($schedule) {
                if ($schedule->day_of_week === $today) {
                    // Add 1-minute grace period past schedule end_time (e.g. ends at 11:20 -> alert at 11:21+)
                    $endTimeCarbon = \Carbon\Carbon::parse($schedule->end_time);
                    $graceEndTime = $endTimeCarbon->copy()->addMinute();

                    if (now()->format('H:i:s') >= $graceEndTime->format('H:i:s')) {
                        $isExpired = true;
                        $endTimeFormatted = $endTimeCarbon->format('h:i A');
                        $expiredReason = "Your scheduled access on " . ucfirst($today) . " ended at {$endTimeFormatted}, but Key {$key->key_name} (Slot #{$key->slot_number}) has NOT yet been returned.";
                    }
                } else {
                    // Scheduled for another day (e.g. yesterday) and key is still not returned today
                    $isExpired = true;
                    $expiredReason = "Your schedule was for " . ucfirst($schedule->day_of_week) . ", but Key {$key->key_name} (Slot #{$key->slot_number}) has NOT yet been returned today.";
                }
            } else {
                // If user has no specific schedule, flag if borrowed over 1 hour ago
                if ($tx->borrowed_at && $tx->borrowed_at->diffInMinutes(now()) >= 60) {
                    $isExpired = true;
                    $expiredReason = "Key {$key->key_name} (Slot #{$key->slot_number}) was borrowed {$tx->borrowed_at->diffForHumans()} and has not been returned.";
                }
            }

            // IF SCHEDULE IS NOT EXPIRED: DO NOT SEND EMAIL!
            if (!$isExpired) {
                $this->line("  [ACTIVE] Slot #{$key->slot_number} borrowed by {$borrower->name} - Schedule still active / within time window.");
                continue;
            }

            $expiredCount++;
            $this->warn("  [EXPIRED] Slot #{$key->slot_number} borrowed by {$borrower->name} - {$expiredReason}");

            // 3. Cooldown check: prevent sending emails every single minute (30 min cooldown per transaction)
            $cooldownKey = 'unreturned_alert_cooldown_' . $tx->id;
            if (!$this->option('force') && Cache::has($cooldownKey)) {
                $this->line("    --> Email notification on cooldown (already alerted recently).");
                continue;
            }

            Cache::put($cooldownKey, true, now()->addMinutes(30));

            // 4. Send Email to Borrower
            if (!empty($borrower->email) && filter_var($borrower->email, FILTER_VALIDATE_EMAIL)) {
                try {
                    Mail::to($borrower->email)->send(new KeyUnreturnedUserNotice($borrower, $key, $tx, $expiredReason));
                    $this->info("    --> Alert email sent to borrower: {$borrower->email}");
                } catch (\Throwable $e) {
                    $this->error("    --> Failed to email borrower: " . $e->getMessage());
                    Log::error("[UNRETURNED EMAIL] Failed to email borrower: " . $e->getMessage());
                }
            }

            // 5. Send Email to All System Admins
            foreach ($admins as $admin) {
                if (filter_var($admin->email, FILTER_VALIDATE_EMAIL)) {
                    try {
                        Mail::to($admin->email)->send(new KeyUnreturnedAdminAlert($admin, $borrower, $key, $tx, $expiredReason));
                        $this->info("    --> Alert email sent to admin: {$admin->email}");
                    } catch (\Throwable $e) {
                        $this->error("    --> Failed to email admin: " . $e->getMessage());
                        Log::error("[UNRETURNED EMAIL] Failed to email admin: " . $e->getMessage());
                    }
                }
            }

            // 6. Mark the key as 'missing' in the database since the schedule has expired
            // and the key has not been returned. Only flag if it's still 'borrowed' to avoid
            // overwriting a status that may have been manually corrected.
            if ($key->status === 'borrowed') {
                try {
                    $key->update(['status' => 'missing']);
                    $this->warn("    --> Key Slot #{$key->slot_number} status updated to MISSING (schedule expired).");

                    // Broadcast real-time status update so the web dashboard reflects instantly
                    try {
                        KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'missing', $key->key_name, $key->room_name, null);
                        AccessLogged::dispatch(
                            'System',
                            'missing',
                            'denied',
                            "Key auto-flagged MISSING: {$expiredReason}",
                            $key->key_name,
                            $key->room_name
                        );
                    } catch (\Throwable $e) {
                        Log::warning("[UNRETURNED] Broadcast skipped (server unreachable): " . $e->getMessage());
                    }
                } catch (\Throwable $e) {
                    $this->error("    --> Failed to mark key as missing: " . $e->getMessage());
                    Log::error("[UNRETURNED KEY] Failed to update key status to missing: " . $e->getMessage());
                }
            }

            // 7. Record audit log so the event is visible on the web dashboard
            try {
                AccessLog::create([
                    'user_id'    => $borrower->id,
                    'qr_token'   => $borrower->qr_token ?? 'SYSTEM_ALERT',
                    'action'     => 'alert_unreturned',
                    'result'     => 'denied',
                    'reason'     => "Overdue Notice: Key auto-flagged MISSING. {$expiredReason}",
                    'ip_address' => '127.0.0.1',
                ]);
            } catch (\Throwable $e) {
                Log::warning("[UNRETURNED EMAIL] Failed to log to access_logs: " . $e->getMessage());
            }
        }

        $this->info("Finished scan. Processed {$expiredCount} expired unreturned key(s).");
        return Command::SUCCESS;
    }
}
