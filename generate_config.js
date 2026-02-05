#!/usr/bin/env node
// Читает .env в папке Игра и пишет config.js с window.GAME_API_BASE.
const fs = require('fs');
const path = require('path');

const envPath = path.join(__dirname, '.env');
const configPath = path.join(__dirname, 'config.js');

let apiBase = '';
if (fs.existsSync(envPath)) {
  const content = fs.readFileSync(envPath, 'utf8');
  const m = content.match(/API_BASE=(.*)/);
  if (m) apiBase = (m[1] || '').trim().replace(/^["']|["']$/g, '');
}

const line = "window.GAME_API_BASE = " + JSON.stringify(apiBase) + ";\n";
fs.writeFileSync(configPath, "// Сгенерировано из .env (generate_config.js)\n" + line);
console.log("config.js обновлён: GAME_API_BASE =", apiBase || "(пусто)");
