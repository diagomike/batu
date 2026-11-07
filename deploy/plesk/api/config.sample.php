<?php
/* Copy this file to config.php in the same folder and fill it in (see DEPLOY.md).
   config.php is never overwritten by Publish, so your settings and passwords stay on the server. */
return [
    // Database: 'sqlite' needs no setup; 'mysql' uses the database from Plesk > Databases.
    'db' => 'sqlite',
    // SQLite file OUTSIDE the public web folder. In Plesk the site folder is usually
    // /var/www/vhosts/batu.gov.et/httpdocs, so its parent is a safe place:
    'sqlite_path' => dirname(__DIR__, 2) . '/private/batu.sqlite',

    'mysql_dsn' => 'mysql:host=localhost;dbname=batu_portal;charset=utf8mb4',
    'mysql_user' => 'batu_portal',
    'mysql_password' => '',

    // Photos residents attach to reports, also outside the public folder.
    'uploads_dir' => dirname(__DIR__, 2) . '/private/uploads',

    // Lets the studio read requests and update their status (REMOTE_API_TOKEN in the studio's .env).
    // Use a long random value, at least 24 characters. Empty switches the admin API off.
    'admin_token' => '',

    // Online payment: 'off' (the pay page explains how to pay at the office),
    // 'demo' (test checkout, no money moves; for trials only), later 'telebirr'.
    'payments' => 'off',
];
