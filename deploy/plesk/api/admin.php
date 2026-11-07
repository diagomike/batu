<?php
/* Admin API for Batu Studio (the studio sets REMOTE_API and REMOTE_API_TOKEN in its .env).
   GET  /api/admin/requests            list of requests
   GET  /api/admin/requests/<ref>      one request with the resident's details
   POST /api/admin/status              {ref, status, note, by}
   GET  /api/admin/subscriptions       sign-ups for notices
   Token in "Authorization: Bearer <token>" or "X-Api-Token: <token>"; set admin_token in config.php. */
require __DIR__ . '/lib.php';

$token = (string)cfg('admin_token', '');
if (strlen($token) < 24) json_out(['error' => 'The admin API is switched off (admin_token in config.php).'], 503);
$given = $_SERVER['HTTP_X_API_TOKEN'] ?? '';
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? ($_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '');
if ($given === '' && stripos($auth, 'Bearer ') === 0) $given = substr($auth, 7);
if (!hash_equals($token, trim((string)$given))) {
    rate_limit('admin-fail', 10, 900);
    json_out(['error' => 'wrong token'], 403);
}

$action = (string)($_GET['action'] ?? '');
if ($action === 'requests') {
    $limit = max(1, min(1000, (int)($_GET['limit'] ?? 200)));
    $rows = db()->query("SELECT ref,kind,title,status,amount,paid,created FROM requests ORDER BY created DESC LIMIT $limit")->fetchAll();
    foreach ($rows as &$r) { $r['status_label'] = status_label($r['status']); $r['paid'] = (int)$r['paid']; }
    json_out($rows);
}
if ($action === 'request') {
    $r = get_request((string)($_GET['ref'] ?? ''));
    if (!$r) json_out(['error' => 'not found'], 404);
    json_out($r);
}
if ($action === 'status' && ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
    $in = json_decode((string)file_get_contents('php://input'), true) ?: $_POST;
    $status = (string)($in['status'] ?? '');
    if (!isset(cat('statuses')[$status])) json_out(['error' => 'unknown status'], 400);
    if (!set_status((string)($in['ref'] ?? ''), $status, trim((string)($in['note'] ?? '')))) json_out(['error' => 'not found'], 404);
    json_out(['ok' => true]);
}
if ($action === 'subscriptions') {
    json_out(db()->query('SELECT * FROM subscriptions ORDER BY id DESC')->fetchAll());
}
json_out(['error' => 'unknown action'], 404);
