// Конфиг включения экранов и фич (по плану модульности).
// Меняйте флаги, чтобы отключать части без правки остального кода.
window.GAME_FEATURES = {
  screens: {
    village: true,
    mine: true,
    inventory: true,
    market: true,
    profile: true,
    pnl: true,
    tasks: true,
    rating: true,
    help: true  // Обучение (📖) — контент из frontend/data/help-content.js + frontend/js/help.js
  },
  marketOrders: true,
  aboutCatalog: true
};
