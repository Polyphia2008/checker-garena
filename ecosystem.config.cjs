module.exports = {
  apps: [
    {
      name: 'Minhnhatdev-php',
      script: '/usr/bin/php',
      args: '-S 0.0.0.0:3000 -t /home/user/webapp/public',
      cwd: '/home/user/webapp/public',
      env: {
        PHP_CLI_SERVER_WORKERS: 10
      },
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true
    }
  ]
}
