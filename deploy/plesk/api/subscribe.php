<?php
/* Sign up for notices by SMS, email or Telegram (form on /news). Mirrors POST /subscribe in app/main.py. */
require __DIR__ . '/lib.php';
require_post();
rate_limit('subscribe', 6, 3600);

$contact = field('contact', 200);
if ($contact === '') fail('Please give a phone number or email address.');
$channel = in_array(field('channel', 20), ['sms', 'email', 'telegram'], true) ? field('channel', 20) : 'sms';
db()->prepare('INSERT INTO subscriptions(at, channel, contact, topics) VALUES(?,?,?,?)')
    ->execute([now(), $channel, $contact, field('topics', 200) ?: 'notices']);
go(lang_prefix() . 'news/?subscribed=1#notices');
