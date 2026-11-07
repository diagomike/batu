<?php
/* Online payment. Mirrors /pay and /pay/demo-checkout in app/main.py.
   POST /api/pay            {ref}           -> start a payment, answer with the checkout address
   GET  /api/pay?pid=...                    -> a payment, for the checkout and receipt screens
   POST /api/pay?confirm=1  {pid, result}   -> finish the demo checkout
   With 'payments' => 'off' in config.php every call explains how to pay at the office instead. */
require __DIR__ . '/lib.php';

$mode = cfg('payments', 'off');
if ($mode !== 'demo') {
    // Telebirr goes here once the city has a merchant account (see DEPLOY.md).
    json_out(['error' => 'Online payment is not switched on yet. Please pay at the Revenue Office and keep your reference number.',
              'payments' => $mode], 503);
}

function payment(string $pid): ?array {
    $st = db()->prepare('SELECT * FROM payments WHERE id=?');
    $st->execute([$pid]);
    $p = $st->fetch();
    return $p ?: null;
}

function payment_out(array $p): array {
    $r = get_request($p['request_ref']);
    return ['id' => $p['id'], 'amount' => (float)$p['amount'], 'status' => $p['status'], 'receipt' => $p['receipt'],
            'provider' => $p['provider'], 'created' => $p['created'],
            'request' => $r ? ['ref' => $r['ref'], 'title' => $r['title'], 'kind' => $r['kind']] : null];
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$in = $_POST;
if ($method === 'POST' && stripos($_SERVER['CONTENT_TYPE'] ?? '', 'application/json') !== false) {
    $in = json_decode((string)file_get_contents('php://input'), true) ?: [];
}

if ($method === 'GET') {
    $p = payment((string)($_GET['pid'] ?? ''));
    if (!$p) json_out(['error' => 'not found'], 404);
    json_out(payment_out($p));
}

if (empty($_GET['confirm'])) {
    rate_limit('pay', 20, 600);
    $r = get_request((string)($in['ref'] ?? ''));
    if (!$r) json_out(['error' => 'No bill or request has that reference.'], 404);
    if (!$r['amount'] || $r['paid']) json_out(['error' => 'There is nothing to pay on this reference.'], 409);
    $pid = 'PAY-' . strtoupper(bin2hex(random_bytes(4)));
    db()->prepare('INSERT INTO payments(id,request_ref,amount,provider,status,created) VALUES(?,?,?,?,?,?)')
        ->execute([$pid, $r['ref'], $r['amount'], 'demo', 'pending', now()]);
    json_out(['pid' => $pid]);
}

// confirm (demo checkout)
$p = payment((string)($in['pid'] ?? ''));
if (!$p) json_out(['error' => 'not found'], 404);
if (($in['result'] ?? '') !== 'success') json_out(['ok' => false, 'ref' => $p['request_ref']]);
if ($p['status'] !== 'paid') {
    $receipt = 'RCT-' . strtoupper(bin2hex(random_bytes(4)));
    db()->prepare("UPDATE payments SET status='paid', receipt=? WHERE id=?")->execute([$receipt, $p['id']]);
    db()->prepare('UPDATE requests SET paid=1 WHERE ref=?')->execute([$p['request_ref']]);
    $r = get_request($p['request_ref']);
    if ($r) {
        set_status($r['ref'], 'paid', "Payment received, receipt $receipt");
        set_status($r['ref'], $r['kind'] === 'booking' ? 'scheduled' : ($r['kind'] === 'bill' ? 'closed' : 'in_review'), '');
    }
    $p = payment($p['id']);
}
json_out(['ok' => true] + payment_out($p));
