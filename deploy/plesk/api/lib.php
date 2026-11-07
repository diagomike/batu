<?php
/* Batu portal: shared code for the PHP services on the Plesk host.
   Mirrors app/db.py (requests, payments, subscriptions) so the studio can manage both.
   Needs PHP 7.4+ with PDO (pdo_sqlite or pdo_mysql). Settings live in api/config.php. */
declare(strict_types=1);

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) { http_response_code(404); exit; }

date_default_timezone_set('Africa/Addis_Ababa');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');

$cfgFile = __DIR__ . '/config.php';
if (!is_file($cfgFile)) {
    http_response_code(503);
    header('Content-Type: text/plain; charset=utf-8');
    echo "City services are not set up yet. Copy api/config.sample.php to api/config.php (see DEPLOY.md).";
    exit;
}
// Kept in $GLOBALS so it works however this file is included.
$GLOBALS['BATU_CFG'] = require $cfgFile;
$GLOBALS['BATU_CAT'] = json_decode((string)file_get_contents(__DIR__ . '/data/catalogue.json'), true);

function cfg(string $key, $default = null) { return $GLOBALS['BATU_CFG'][$key] ?? $default; }
function cat(string $key) { return $GLOBALS['BATU_CAT'][$key] ?? []; }

/* ---------- database ---------- */
function db(): PDO {
    static $pdo = null;
    if ($pdo) return $pdo;
    $opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC];
    if (cfg('db', 'sqlite') === 'mysql') {
        $pdo = new PDO(cfg('mysql_dsn'), cfg('mysql_user'), cfg('mysql_password'), $opts);
        $pdo->exec('SET NAMES utf8mb4');
    } else {
        $path = cfg('sqlite_path');
        if (!is_dir(dirname($path))) mkdir(dirname($path), 0750, true);
        $pdo = new PDO('sqlite:' . $path, null, null, $opts);
        $pdo->exec('PRAGMA journal_mode=WAL');
        $pdo->exec('PRAGMA busy_timeout=4000');
    }
    schema($pdo);
    return $pdo;
}

function is_mysql(): bool { return cfg('db', 'sqlite') === 'mysql'; }

function schema(PDO $pdo): void {
    $auto = is_mysql() ? 'INT AUTO_INCREMENT PRIMARY KEY' : 'INTEGER PRIMARY KEY AUTOINCREMENT';
    $tail = is_mysql() ? ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4' : '';
    $pdo->exec("CREATE TABLE IF NOT EXISTS requests (ref VARCHAR(40) PRIMARY KEY, kind VARCHAR(20) NOT NULL, service_id VARCHAR(80),
        title VARCHAR(300), data TEXT NOT NULL, status VARCHAR(30) NOT NULL, amount DOUBLE, paid INTEGER NOT NULL DEFAULT 0,
        created VARCHAR(25) NOT NULL, updated VARCHAR(25) NOT NULL, history TEXT NOT NULL)$tail");
    $pdo->exec("CREATE TABLE IF NOT EXISTS payments (id VARCHAR(20) PRIMARY KEY, request_ref VARCHAR(40) NOT NULL, amount DOUBLE NOT NULL,
        provider VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, created VARCHAR(25) NOT NULL, receipt VARCHAR(20))$tail");
    $pdo->exec("CREATE TABLE IF NOT EXISTS subscriptions (id $auto, at VARCHAR(25) NOT NULL, channel VARCHAR(20) NOT NULL,
        contact VARCHAR(200) NOT NULL, topics VARCHAR(200))$tail");
    $pdo->exec("CREATE TABLE IF NOT EXISTS hits (bucket VARCHAR(80) NOT NULL, at INTEGER NOT NULL)$tail");
    // A sample bill so the payment flow can be tried end to end (remove it in the studio once real bills exist).
    $ins = is_mysql() ? 'INSERT IGNORE' : 'INSERT OR IGNORE';
    $t = now();
    $h = json_encode([['at' => $t, 'status' => 'awaiting_payment', 'note' => 'Bill issued']]);
    $st = $pdo->prepare("$ins INTO requests(ref,kind,service_id,title,data,status,amount,paid,created,updated,history) VALUES(?,?,?,?,?,?,?,?,?,?,?)");
    $st->execute(['LL-BTU-0001', 'bill', 'land-lease-payment', 'Land lease instalment 2019 E.C. (sample bill)',
        json_encode(['holder' => 'Sample land holder', 'plot' => 'Plot B-114 (sample)']), 'awaiting_payment', 4200, 0, $t, $t, $h]);
}

function now(): string { return date('Y-m-d\TH:i:s'); }

function new_ref(string $prefix): string {
    return 'BTU-' . $prefix . '-' . date('ym') . '-' . strtoupper(bin2hex(random_bytes(2)));
}

function status_label(string $s): string { $l = cat('statuses'); return $l[$s] ?? $s; }

function create_request(string $kind, string $prefix, ?string $service, string $title, array $data, $amount = null): string {
    $status = $amount ? 'awaiting_payment' : 'received';
    $t = now();
    $hist = json_encode([['at' => $t, 'status' => $status, 'note' => $status === 'awaiting_payment' ? 'Bill issued' : 'Request received']]);
    for ($i = 0; $i < 5; $i++) {
        $ref = new_ref($prefix);
        try {
            db()->prepare('INSERT INTO requests(ref,kind,service_id,title,data,status,amount,paid,created,updated,history) VALUES(?,?,?,?,?,?,?,?,?,?,?)')
                ->execute([$ref, $kind, $service, $title, json_encode($data, JSON_UNESCAPED_UNICODE), $status, $amount, 0, $t, $t, $hist]);
            return $ref;
        } catch (PDOException $e) { /* reference taken: try another */ }
    }
    throw new RuntimeException('could not create a reference');
}

function get_request(string $ref): ?array {
    $st = db()->prepare('SELECT * FROM requests WHERE UPPER(ref)=UPPER(?)');
    $st->execute([trim($ref)]);
    $r = $st->fetch();
    if (!$r) return null;
    $r['data'] = json_decode($r['data'], true) ?: [];
    $r['history'] = json_decode($r['history'], true) ?: [];
    $r['status_label'] = status_label($r['status']);
    $r['paid'] = (int)$r['paid'];
    $r['amount'] = $r['amount'] === null ? null : (float)$r['amount'];
    return $r;
}

function set_status(string $ref, string $status, string $note = ''): bool {
    $r = get_request($ref);
    if (!$r) return false;
    $r['history'][] = ['at' => now(), 'status' => $status, 'note' => $note !== '' ? $note : status_label($status)];
    db()->prepare('UPDATE requests SET status=?, updated=?, history=? WHERE ref=?')
        ->execute([$status, now(), json_encode($r['history'], JSON_UNESCAPED_UNICODE), $r['ref']]);
    return true;
}

/* ---------- requests from the browser ---------- */
function lang_prefix(): string {
    $l = $_GET['lang'] ?? '';
    return in_array($l, ['om', 'am'], true) ? "/$l/" : '/';
}

function field(string $key, int $max = 2000): string {
    $v = $_POST[$key] ?? '';
    if (!is_string($v)) return '';
    $v = trim(str_replace("\r\n", "\n", $v));
    return function_exists('mb_substr') ? mb_substr($v, 0, $max) : substr($v, 0, $max);
}

function wants_json(): bool {
    return stripos($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json') !== false;
}

function json_out($data, int $code = 200): void {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function go(string $url): void {
    if (wants_json()) json_out(['ok' => true, 'next' => $url]);
    header('Location: ' . $url, true, 303);
    exit;
}

/** A plain page for problems when the visitor has no JavaScript; JSON otherwise. */
function fail(string $message, int $code = 400): void {
    if (wants_json()) json_out(['error' => $message], $code);
    http_response_code($code);
    header('Content-Type: text/html; charset=utf-8');
    $m = htmlspecialchars($message, ENT_QUOTES, 'UTF-8');
    echo "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
       . "<title>Batu</title><body style='font:16px/1.5 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px'>"
       . "<h1 style='font-size:1.4rem'>$m</h1><p><a href='javascript:history.back()'>&larr; Back</a> · <a href='/'>Home</a></p>";
    exit;
}

function require_post(): void {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') fail('Please use the form on the website.', 405);
}

function client_ip(): string { return substr((string)($_SERVER['REMOTE_ADDR'] ?? '?'), 0, 64); }

/** Allow $max actions per $window seconds for this visitor in a bucket; stop with 429 beyond that. */
function rate_limit(string $bucket, int $max, int $window): void {
    $key = $bucket . ':' . client_ip();
    $since = time() - $window;
    $pdo = db();
    if (random_int(1, 50) === 1) $pdo->prepare('DELETE FROM hits WHERE at < ?')->execute([time() - 86400]);
    $st = $pdo->prepare('SELECT COUNT(*) FROM hits WHERE bucket=? AND at>=?');
    $st->execute([$key, $since]);
    if ((int)$st->fetchColumn() >= $max) fail('Too many tries in a short time. Please wait a few minutes and try again.', 429);
    $pdo->prepare('INSERT INTO hits(bucket, at) VALUES(?, ?)')->execute([$key, time()]);
}

/** Only fields a member of the public may see about a request: no names, phones or details. */
function public_request(array $r): array {
    $hist = array_map(function ($h) { return ['at' => $h['at'], 'status' => $h['status'], 'note' => $h['note']]; }, $r['history']);
    return ['ref' => $r['ref'], 'kind' => $r['kind'], 'title' => $r['title'], 'status' => $r['status'],
        'status_label' => $r['status_label'], 'amount' => $r['amount'], 'paid' => $r['paid'],
        'created' => $r['created'], 'updated' => $r['updated'], 'history' => $hist];
}
