module.exports = {
  apps: [
    {
      name: 'garena-checker',
      script: 'python3',
      args: 'app.py',
      env: {
        PYTHONUNBUFFERED: '1',
        FLASK_ENV: 'development',
        PORT: 3000,
      },
      watch: false,
      instances: 1,
      exec_mode: 'fork',
    }
  ]
};
