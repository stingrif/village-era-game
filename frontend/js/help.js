/**
 * Модуль «Обучение» (📖). Заполняет экран обучения из frontend/data/help-content.js.
 * Зависимости: window.G, window.HELP_SECTIONS (если нет — используется fallback).
 */
(function () {
  function buildHelpHtml() {
    var sections = window.HELP_SECTIONS;
    if (sections && sections.length > 0) {
      return sections.map(function (s) {
        return '<div class="help-section"><h4>' + (s.title || '') + '</h4>' + (s.body || '') + '</div>';
      }).join('');
    }
    // Fallback: минимальный текст, если data не загружен
    return '<div class="help-section"><h4>📖 Обучение</h4><p>Загрузите <code>frontend/data/help-content.js</code> для полного гайда. Или откройте <strong>О проекте</strong> (ℹ️) для каталога предметов.</p></div>';
  }

  function openHelp() {
    var container = document.getElementById('helpmc');
    if (container) container.innerHTML = buildHelpHtml();
    if (window.G && typeof window.G.openM === 'function') window.G.openM('helpModal');
  }

  if (window.G) {
    window.G.openHelp = openHelp;
  } else {
    window.addEventListener('load', function () {
      if (window.G) window.G.openHelp = openHelp;
    });
  }
})();
