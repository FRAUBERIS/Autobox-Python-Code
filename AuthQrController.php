<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\User;
use App\Models\Key;
use App\Models\Transaction;
use App\Models\AccessLog;
use App\Models\Schedule;
use App\Events\SliderStateChanged;
use App\Events\KeyStatusUpdated;
use App\Events\AccessLogged;
use App\Mail\QrMultipleScansAdminAlert;
use App\Mail\QrMultipleScansUserWarning;
use App\Mail\KeyUnreturnedUserNotice;
use App\Mail\KeyUnreturnedAdminAlert;
use App\Mail\KeyPhysicallyRemovedAlert;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Mail;
use Illuminate\Support\Facades\Log;

class AuthQrController extends Controller
{
    /**
     * Authenticate QR code scanned by hardware scanner
     */
    public function authenticate(Request $request)
    {
        $request->validate([
            'qr_token'    => 'required|string',
            'slot_number' => 'nullable|integer',
        ]);

        $qrToken = $request->qr_token;
        $ip = $request->ip();

        // 1. Find User by QR token
        $user = User::where('qr_token', $qrToken)->where('is_active', true)->first();

        // 2. Track scan frequency for 3-scan security alert
        $this->handleScanFrequencySecurityCheck($user, $qrToken, $ip);

        if (!$user) {
            AccessLog::create([
                'user_id'    => null,
                'qr_token'   => $qrToken,
                'action'     => 'scan',
                'result'     => 'denied',
                'reason'     => 'Invalid or inactive QR code',
                'ip_address' => $ip,
            ]);

            return response()->json([
                'success' => false,
                'status'  => 'DENIED',
                'message' => 'Invalid or inactive QR Code',
            ], 401);
        }

        // 3. Determine action: Is user returning a currently borrowed key?
        $existingBorrow = Transaction::where('user_id', $user->id)
            ->where('action', 'borrow')
            ->whereNull('returned_at')
            ->latest()
            ->first();

        if ($existingBorrow) {
            // ACTION: RETURN KEY
            $key = $existingBorrow->key;
            if (!$key) {
                return response()->json([
                    'success' => false,
                    'status'  => 'DENIED',
                    'message' => 'Key record not found',
                ], 404);
            }

            $existingBorrow->update([
                'returned_at' => now(),
            ]);

            Transaction::create([
                'user_id'     => $user->id,
                'key_id'      => $key->id,
                'action'      => 'return',
                'status'      => 'success',
                'notes'       => 'Returned via QR Scan',
                'returned_at' => now(),
            ]);

            $key->update(['status' => 'available']);

            AccessLog::create([
                'user_id'    => $user->id,
                'qr_token'   => $qrToken,
                'action'     => 'return',
                'result'     => 'granted',
                'reason'     => "Key returned to Slot #{$key->slot_number}",
                'ip_address' => $ip,
            ]);

            $this->safeBroadcast(function () use ($key, $user) {
                KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'available', $key->key_name, $key->room_name, null);
                AccessLogged::dispatch($user->name, 'return', 'granted', "Returned to Slot #{$key->slot_number}", $key->key_name, $key->room_name);
            });

            return response()->json([
                'success'     => true,
                'status'      => 'GRANTED',
                'action'      => 'RETURN',
                'slot_number' => $key->slot_number,
                'key_name'    => $key->key_name,
                'user_name'   => $user->name,
                'message'     => "Access Granted: Return Key to Slot #{$key->slot_number}",
            ]);
        }

        $today = strtolower(now()->format('l'));
        $currentTime = now()->format('H:i:s');
        $key = null;

        if ($user->role === 'admin') {
            AccessLog::create([
                'user_id'    => $user->id,
                'qr_token'   => $qrToken,
                'action'     => 'admin_access',
                'result'     => 'granted',
                'reason'     => 'Admin Access: Main lockbox door opened',
                'ip_address' => $ip,
            ]);

            $this->safeBroadcast(function () use ($user) {
                AccessLogged::dispatch($user->name, 'admin_access', 'granted', 'Admin Access: Door opened', null, null);
            });

            return response()->json([
                'success'     => true,
                'status'      => 'GRANTED',
                'action'      => 'ADMIN_DOOR_OPEN',
                'slot_number' => null,
                'key_name'    => 'Lock Box Main Door',
                'user_name'   => $user->name,
                'message'     => 'Admin Access: Opening Door',
            ]);
        } else {
            $schedule = Schedule::where('user_id', $user->id)
                ->where('day_of_week', $today)
                ->where('is_active', true)
                ->where('start_time', '<=', $currentTime)
                ->where('end_time', '>=', $currentTime)
                ->with('key')
                ->first();

            if (!$schedule) {
                $todaySchedule = Schedule::where('user_id', $user->id)
                    ->where('day_of_week', $today)
                    ->where('is_active', true)
                    ->first();

                $otherSchedule = Schedule::where('user_id', $user->id)
                    ->where('is_active', true)
                    ->first();

                if ($todaySchedule) {
                    $reason = "Access Denied: Scheduled on " . ucfirst($today) . " from " .
                        \Carbon\Carbon::parse($todaySchedule->start_time)->format('h:i A') . " to " .
                        \Carbon\Carbon::parse($todaySchedule->end_time)->format('h:i A');
                } elseif ($otherSchedule) {
                    $reason = "Access Denied: Your schedule is for " . ucfirst($otherSchedule->day_of_week) . ", but today is " . ucfirst($today);
                } else {
                    $reason = "Access Denied: No active schedule assigned for today (" . ucfirst($today) . ")";
                }

                AccessLog::create([
                    'user_id'    => $user->id,
                    'qr_token'   => $qrToken,
                    'action'     => 'borrow',
                    'result'     => 'denied',
                    'reason'     => $reason,
                    'ip_address' => $ip,
                ]);

                $this->safeBroadcast(function () use ($user, $reason) {
                    AccessLogged::dispatch($user->name, 'borrow', 'denied', $reason, null, null);
                });

                return response()->json([
                    'success' => false,
                    'status'  => 'DENIED',
                    'message' => $reason,
                ], 403);
            }

            $key = $schedule->key;
        }

        if (!$key) {
            AccessLog::create([
                'user_id'    => $user->id,
                'qr_token'   => $qrToken,
                'action'     => 'scan',
                'result'     => 'denied',
                'reason'     => 'No key assigned or available for this schedule',
                'ip_address' => $ip,
            ]);

            return response()->json([
                'success' => false,
                'status'  => 'DENIED',
                'message' => 'No key assigned or available for access',
            ], 404);
        }

        if ($key->status === 'borrowed') {
            AccessLog::create([
                'user_id'    => $user->id,
                'qr_token'   => $qrToken,
                'action'     => 'borrow',
                'result'     => 'denied',
                'reason'     => "Key Slot #{$key->slot_number} is already borrowed",
                'ip_address' => $ip,
            ]);

            $this->safeBroadcast(function () use ($user, $key) {
                AccessLogged::dispatch($user->name, 'borrow', 'denied', "Slot #{$key->slot_number} already borrowed", $key->key_name, $key->room_name);
            });

            return response()->json([
                'success' => false,
                'status'  => 'DENIED',
                'message' => "Key is currently borrowed by another user",
            ], 409);
        }

        Transaction::create([
            'user_id'     => $user->id,
            'key_id'      => $key->id,
            'action'      => 'borrow',
            'status'      => 'success',
            'notes'       => 'Borrowed via QR Scan',
            'borrowed_at' => now(),
        ]);

        $key->update(['status' => 'borrowed']);

        AccessLog::create([
            'user_id'    => $user->id,
            'qr_token'   => $qrToken,
            'action'     => 'borrow',
            'result'     => 'granted',
            'reason'     => "Key Slot #{$key->slot_number} unlocked for borrowing",
            'ip_address' => $ip,
        ]);

        $this->safeBroadcast(function () use ($key, $user) {
            KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'borrowed', $key->key_name, $key->room_name, $user->name);
            AccessLogged::dispatch($user->name, 'borrow', 'granted', "Borrowed Slot #{$key->slot_number}", $key->key_name, $key->room_name);
        });

        return response()->json([
            'success'     => true,
            'status'      => 'GRANTED',
            'action'      => 'BORROW',
            'slot_number' => $key->slot_number,
            'key_name'    => $key->key_name,
            'user_name'   => $user->name,
            'message'     => "Access Granted: Unlock Slot #{$key->slot_number}",
        ]);
    }

    /**
     * Handle security check and multi-scan alerting when QR is scanned 3 or more times.
     */
    protected function handleScanFrequencySecurityCheck(?User $user, string $qrToken, string $ip): void
    {
        $cacheKey = 'qr_scan_count_' . md5($qrToken);
        $cooldownKey = 'qr_alert_cooldown_' . md5($qrToken);

        $scanCount = (int) Cache::get($cacheKey, 0) + 1;
        Cache::put($cacheKey, $scanCount, now()->addMinutes(15));

        // When scanned 3 or more times, trigger alert (with 15 min cooldown to prevent mail spam)
        if ($scanCount >= 3 && !Cache::has($cooldownKey)) {
            Cache::put($cooldownKey, true, now()->addMinutes(15));

            $userName = $user ? $user->name : 'Unknown User (Unregistered QR)';

            // 1. Log security alert
            AccessLog::create([
                'user_id'    => $user?->id,
                'qr_token'   => $qrToken,
                'action'     => 'security_alert',
                'result'     => 'denied',
                'reason'     => "SECURITY ALERT: QR Code scanned {$scanCount} times within 15 minutes",
                'ip_address' => $ip,
            ]);

            // 2. Dispatch real-time WebSocket event for instant admin screen alert safely
            $this->safeBroadcast(function () use ($userName, $scanCount) {
                AccessLogged::dispatch(
                    $userName,
                    'security_alert',
                    'denied',
                    "SECURITY ALERT: QR code was scanned {$scanCount} times rapidly!",
                    null,
                    null
                );
            });

            // 3. Send email to all Admins
            try {
                $admins = User::where('role', 'admin')->whereNotNull('email')->get();
                foreach ($admins as $admin) {
                    if (filter_var($admin->email, FILTER_VALIDATE_EMAIL)) {
                        Mail::to($admin->email)->send(new QrMultipleScansAdminAlert($user, $qrToken, $scanCount, $ip));
                    }
                }
            } catch (\Throwable $e) {
                Log::error("[SECURITY ALERT] Failed to send admin alert email: " . $e->getMessage());
            }

            // 4. Send email to the User who owns that QR code
            if ($user && !empty($user->email) && filter_var($user->email, FILTER_VALIDATE_EMAIL)) {
                try {
                    Mail::to($user->email)->send(new QrMultipleScansUserWarning($user, $scanCount));
                } catch (\Throwable $e) {
                    Log::error("[SECURITY ALERT] Failed to send user warning email: " . $e->getMessage());
                }
            }
        }
    }

    /**
     * Safely dispatch real-time events without crashing if Reverb/Pusher is unreachable.
     */
    protected function safeBroadcast(callable $callback): void
    {
        try {
            $callback();
        } catch (\Throwable $e) {
            Log::warning("[BROADCAST] Event dispatch skipped (broadcast server unreachable): " . $e->getMessage());
        }
    }

    /**
     * Get real-time status of all key slots
     */
    public function getKeyStatuses()
    {
        $keys = Key::orderBy('slot_number')->get(['id', 'key_name', 'room_name', 'slot_number', 'status']);
        return response()->json([
            'success' => true,
            'keys'    => $keys,
        ]);
    }

    /**
     * Hardware reports key missing
     */
    public function reportMissing(Request $request)
    {
        $request->validate([
            'slot_number' => 'required|integer',
            'reason'      => 'nullable|string|in:unauthorized_removal,manual',
        ]);

        $key = Key::where('slot_number', $request->slot_number)->first();
        if ($key) {
            $key->update(['status' => 'missing']);

            // Find borrower using intelligent multi-level fallback
            $borrower   = self::resolveLastBorrower($key);
            $activeBorrow = self::resolveLastTransaction($key);

            $isUnauthorizedRemoval = $request->input('reason') === 'unauthorized_removal';

            if ($isUnauthorizedRemoval) {
                // IR sensor detected physical removal without QR scan — send dedicated theft/intrusion alert
                try {
                    $admins = User::where('role', 'admin')->whereNotNull('email')->get();
                    foreach ($admins as $admin) {
                        if (filter_var($admin->email, FILTER_VALIDATE_EMAIL)) {
                            Mail::to($admin->email)->send(
                                new KeyPhysicallyRemovedAlert($admin, $borrower, $key, $activeBorrow)
                            );
                        }
                    }
                    Log::info("[AUTOBOX SECURITY] Unauthorized removal alert emails sent for Slot #{$key->slot_number}");
                } catch (\Throwable $e) {
                    Log::error("[AUTOBOX SECURITY] Failed to send unauthorized removal email: " . $e->getMessage());
                }
            } else {
                // Standard missing alert (triggered manually or by admin)
                $this->sendUnreturnedMissingAlerts($key, $borrower, $activeBorrow);
            }

            $this->safeBroadcast(function () use ($key, $isUnauthorizedRemoval) {
                KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'missing', $key->key_name, $key->room_name, null);
                $alertMsg = $isUnauthorizedRemoval
                    ? "SECURITY: Key physically removed WITHOUT QR scan from Slot #{$key->slot_number}"
                    : "Key missing from Slot #{$key->slot_number}";
                AccessLogged::dispatch('Hardware Alert', 'missing', 'denied', $alertMsg, $key->key_name, $key->room_name);
            });

            return response()->json(['success' => true, 'message' => "Slot #{$key->slot_number} marked as missing"]);
        }

        return response()->json(['success' => false, 'message' => 'Slot not found'], 404);
    }

    /**
     * Hardware reports slider door movement (opened/closed via Ultrasonic DC Motor)
     */
    public function reportSliderEvent(Request $request)
    {
        $request->validate([
            'state'  => 'required|string|in:opened,closed',
            'reason' => 'nullable|string',
        ]);

        $action = $request->state === 'opened' ? 'slider_open' : 'slider_close';
        $reason = $request->reason ?? ("DC Motor Slider " . ucfirst($request->state));

        AccessLog::create([
            'user_id'    => null,
            'qr_token'   => 'HARDWARE_SLIDER',
            'action'     => $action,
            'result'     => 'granted',
            'reason'     => $reason,
            'ip_address' => $request->ip(),
        ]);

        // Dispatch WebSocket Event safely
        $this->safeBroadcast(function () use ($request, $action, $reason) {
            SliderStateChanged::dispatch($request->state, $reason);
            AccessLogged::dispatch('System / Ultrasonic', $action, 'granted', $reason);
        });

        return response()->json([
            'success' => true,
            'message' => "Slider event recorded: {$request->state}",
        ]);
    }

    /**
     * Intelligently resolve the last person who retrieved/borrowed a given key.
     * Checks: active borrow -> most recent borrow -> most recent transaction -> access log -> schedule
     */
    public static function resolveLastBorrower(Key $key): ?User
    {
        // 1. Active unreturned borrow
        $activeBorrow = Transaction::where('key_id', $key->id)
            ->where('action', 'borrow')
            ->whereNull('returned_at')
            ->latest()
            ->with('user')
            ->first();

        if ($activeBorrow && $activeBorrow->user) {
            return $activeBorrow->user;
        }

        // 2. Most recent borrow transaction (even if returned_at was populated)
        $lastBorrow = Transaction::where('key_id', $key->id)
            ->where('action', 'borrow')
            ->latest()
            ->with('user')
            ->first();

        if ($lastBorrow && $lastBorrow->user) {
            return $lastBorrow->user;
        }

        // 3. Most recent transaction of any type
        $anyLastTx = Transaction::where('key_id', $key->id)
            ->latest()
            ->with('user')
            ->first();

        if ($anyLastTx && $anyLastTx->user) {
            return $anyLastTx->user;
        }

        // 4. Most recent granted access log for this slot
        $lastLog = AccessLog::where('result', 'granted')
            ->where(function ($q) use ($key) {
                $q->where('reason', 'like', "%Slot #{$key->slot_number}%")
                  ->orWhere('reason', 'like', "%{$key->key_name}%");
            })
            ->whereNotNull('user_id')
            ->latest()
            ->with('user')
            ->first();

        if ($lastLog && $lastLog->user) {
            return $lastLog->user;
        }

        // 5. Active schedule assigned to this key
        $sched = Schedule::where('key_id', $key->id)
            ->where('is_active', true)
            ->with('user')
            ->first();

        if ($sched && $sched->user) {
            return $sched->user;
        }

        return null;
    }

    /**
     * Intelligently resolve the last transaction associated with a given key.
     */
    public static function resolveLastTransaction(Key $key): ?Transaction
    {
        return Transaction::where('key_id', $key->id)
            ->where('action', 'borrow')
            ->whereNull('returned_at')
            ->latest()
            ->first()
            ?? Transaction::where('key_id', $key->id)
                ->where('action', 'borrow')
                ->latest()
                ->first()
            ?? Transaction::where('key_id', $key->id)
                ->latest()
                ->first();
    }

    /**
     * Send email notifications when a key is unreturned / missing to both the borrower and admins.
     */
    protected function sendUnreturnedMissingAlerts(Key $key, ?User $borrower, ?Transaction $transaction): void
    {
        // 1. Send reminder/warning email to the borrower who hasn't returned the key
        if ($borrower && !empty($borrower->email) && filter_var($borrower->email, FILTER_VALIDATE_EMAIL)) {
            try {
                Mail::to($borrower->email)->send(new KeyUnreturnedUserNotice($borrower, $key, $transaction));
            } catch (\Throwable $e) {
                Log::error("[UNRETURNED KEY] Failed to send email to borrower: " . $e->getMessage());
            }
        }

        // 2. Send alert email to all System Admins
        try {
            $admins = User::where('role', 'admin')->whereNotNull('email')->get();
            foreach ($admins as $admin) {
                if (filter_var($admin->email, FILTER_VALIDATE_EMAIL)) {
                    Mail::to($admin->email)->send(new KeyUnreturnedAdminAlert($admin, $borrower, $key, $transaction));
                }
            }
        } catch (\Throwable $e) {
            Log::error("[UNRETURNED KEY] Failed to send email to admins: " . $e->getMessage());
        }
    }

    /**
     * Deliver offline cache package for Raspberry Pi local operation.
     */
    public function getOfflineCache()
    {
        // Active users with their schedules
        $users = User::where('is_active', true)
            ->with(['schedules' => function ($q) {
                $q->where('is_active', true)->with('key');
            }])
            ->get();

        $userMap = [];
        foreach ($users as $user) {
            if (!$user->qr_token) {
                continue;
            }

            $schedules = [];
            foreach ($user->schedules as $sched) {
                $schedules[] = [
                    'id'          => $sched->id,
                    'day_of_week' => strtolower($sched->day_of_week),
                    'start_time'  => $sched->start_time,
                    'end_time'    => $sched->end_time,
                    'slot_number' => $sched->key?->slot_number,
                    'key_id'      => $sched->key_id,
                    'key_name'    => $sched->key?->key_name,
                    'room_name'   => $sched->key?->room_name,
                ];
            }

            $userMap[$user->qr_token] = [
                'id'        => $user->id,
                'name'      => $user->name,
                'role'      => $user->role,
                'is_active' => (bool) $user->is_active,
                'schedules' => $schedules,
            ];
        }

        // Keys with current status and active borrower
        $keys = Key::orderBy('slot_number')->get();
        $keyMap = [];
        foreach ($keys as $key) {
            $activeBorrow = null;
            if ($key->status === 'borrowed') {
                $activeBorrow = Transaction::where('key_id', $key->id)
                    ->where('action', 'borrow')
                    ->whereNull('returned_at')
                    ->latest()
                    ->first();
            }

            $keyMap[(int) $key->slot_number] = [
                'id'                  => $key->id,
                'slot_number'         => (int) $key->slot_number,
                'key_name'            => $key->key_name,
                'room_name'           => $key->room_name,
                'status'              => $key->status,
                'borrowed_by_user_id' => $activeBorrow?->user_id,
            ];
        }

        return response()->json([
            'success'   => true,
            'timestamp' => now()->toDateTimeString(),
            'users'     => $userMap,
            'keys'      => $keyMap,
        ]);
    }

    /**
     * Ingest batched offline transactions and access logs from Raspberry Pi.
     */
    public function syncOfflineLogs(Request $request)
    {
        $request->validate([
            'logs'   => 'required|array',
            'logs.*' => 'required|array',
        ]);

        $logs = $request->input('logs');
        $syncedCount = 0;

        foreach ($logs as $item) {
            $type = $item['type'] ?? null;
            $timestamp = isset($item['timestamp']) ? \Carbon\Carbon::parse($item['timestamp']) : now();

            if ($type === 'transaction') {
                $userId     = $item['user_id'] ?? null;
                $keyId      = $item['key_id'] ?? null;
                $slotNumber = $item['slot_number'] ?? null;
                $action     = $item['action'] ?? null;
                $notes      = $item['notes'] ?? 'Recorded via Offline Mode';

                $key = null;
                if ($keyId) {
                    $key = Key::find($keyId);
                } elseif ($slotNumber) {
                    $key = Key::where('slot_number', $slotNumber)->first();
                }

                if ($key && $userId) {
                    $user = User::find($userId);

                    if ($action === 'borrow' && $user && $user->role !== 'admin') {
                        Transaction::create([
                            'user_id'     => $userId,
                            'key_id'      => $key->id,
                            'action'      => 'borrow',
                            'status'      => 'success',
                            'notes'       => $notes,
                            'borrowed_at' => $timestamp,
                            'created_at'  => $timestamp,
                            'updated_at'  => $timestamp,
                        ]);

                        $key->update(['status' => 'borrowed']);

                        $this->safeBroadcast(function () use ($key, $user) {
                            KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'borrowed', $key->key_name, $key->room_name, $user?->name);
                        });
                    } elseif ($action === 'return') {
                        $existingBorrow = Transaction::where('user_id', $userId)
                            ->where('key_id', $key->id)
                            ->where('action', 'borrow')
                            ->whereNull('returned_at')
                            ->latest()
                            ->first();

                        if ($existingBorrow) {
                            $existingBorrow->update([
                                'returned_at' => $timestamp,
                            ]);
                        }

                        Transaction::create([
                            'user_id'     => $userId,
                            'key_id'      => $key->id,
                            'action'      => 'return',
                            'status'      => 'success',
                            'notes'       => $notes,
                            'returned_at' => $timestamp,
                            'created_at'  => $timestamp,
                            'updated_at'  => $timestamp,
                        ]);

                        $key->update(['status' => 'available']);

                        $this->safeBroadcast(function () use ($key) {
                            KeyStatusUpdated::dispatch($key->id, $key->slot_number, 'available', $key->key_name, $key->room_name, null);
                        });
                    }
                    $syncedCount++;
                }
            } elseif ($type === 'access_log') {
                $userId    = $item['user_id'] ?? null;
                $qrToken   = $item['qr_token'] ?? 'OFFLINE_SCAN';
                $action    = $item['action'] ?? 'scan';
                $result    = $item['result'] ?? 'granted';
                $reason    = $item['reason'] ?? 'Offline Scan Event';
                $ipAddress = $item['ip_address'] ?? $request->ip();

                AccessLog::create([
                    'user_id'    => $userId,
                    'qr_token'   => $qrToken,
                    'action'     => $action,
                    'result'     => $result,
                    'reason'     => $reason,
                    'ip_address' => $ipAddress,
                    'created_at' => $timestamp,
                    'updated_at' => $timestamp,
                ]);

                $userName = 'Unknown User';
                if ($userId) {
                    $user = User::find($userId);
                    $userName = $user?->name ?? 'User #' . $userId;
                }

                $this->safeBroadcast(function () use ($userName, $action, $result, $reason) {
                    AccessLogged::dispatch($userName, $action, $result, $reason, null, null);
                });

                $syncedCount++;
            }
        }

        return response()->json([
            'success'      => true,
            'message'      => "Synced {$syncedCount} offline record(s) successfully",
            'synced_count' => $syncedCount,
        ]);
    }
}
