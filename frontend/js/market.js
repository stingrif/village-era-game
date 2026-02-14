// Модуль маркета: ордера от других игроков, покупка по ордеру.
(function () {
  if (!window.GAME_FEATURES || !window.GAME_FEATURES.marketOrders || !window.G) return;
  var G = window.G;

  function renderAvailableOrders(availEl, game) {
    if (!availEl || !game.API_BASE) {
      if (availEl) availEl.innerHTML = '';
      return;
    }
    availEl.innerHTML = '<span style="opacity:.8">Загрузка…</span>';
    fetch(game.API_BASE + '/api/game/market/orders', {
      headers: { 'X-Telegram-User-Id': String(game.myPlayerId || game.d.playerId || 0) }
    })
      .then(function (r) { return r.json(); })
      .then(function (orders) {
        if (!Array.isArray(orders) || orders.length === 0) {
          availEl.innerHTML = '<div class="info" style="text-align:center;opacity:.8">Пока нет ордеров. Реликвии появятся, когда другие игроки выставят их на продажу в блоке «Ваши реликвии для продажи».</div>';
          return;
        }
        var myId = game.myPlayerId || game.d.playerId;
        var html = '';
        orders.forEach(function (o) {
          if (o.seller_id === myId) return;
          var names = (o.items || []).map(function (i) { return i.name; }).filter(Boolean).join(', ') || 'Предмет';
          var rarity = (o.items && o.items[0]) ? o.items[0].rarity : 'fire';
          var col = game.raritySystem[rarity] ? game.raritySystem[rarity].color : '#ff4500';
          var cur = o.pay_currency === 'STARS' ? '⭐' : o.pay_currency === 'DIAMONDS' ? '💎' : '🪙';
          var fee = Math.max(1, Math.floor(o.pay_amount * 0.05));
          html += '<div class="rc" style="border-color:' + col + ';margin-bottom:10px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><div><span style="color:#ffa500;font-weight:700">' + names + '</span></div></div><div style="font-size:11px;opacity:.9;margin-bottom:4px">' + o.pay_amount + ' ' + cur + ' (комиссия 5%: ' + fee + ')</div><button class="btn btn-small btn-success" onclick="G.fillMarketOrder(' + o.id + ')">Купить</button></div>';
        });
        availEl.innerHTML = html || '<div class="info" style="text-align:center;opacity:.7">Пока нет ордеров от других игроков</div>';
      })
      .catch(function () {
        availEl.innerHTML = '<span style="opacity:.7">Не удалось загрузить ордера</span>';
      });
  }

  async function fillMarketOrder(orderId, game) {
    if (!game.API_BASE) {
      game.notify('Подключите API');
      return;
    }
    game.notify('Покупка…');
    try {
      var r = await fetch(game.API_BASE + '/api/game/market/orders/' + orderId + '/fill', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-User-Id': String(game.myPlayerId || game.d.playerId || 0)
        }
      });
      var j = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        game.notify(j.detail || 'Ошибка покупки', 'error');
        return;
      }
      game.notify('Покупка выполнена!');
      game.loadGame();
      game.renderMarketRelics();
      game.updateUI();
    } catch (e) {
      game.notify('Ошибка сети', 'error');
    }
  }

  window.MarketModule = {
    renderAvailableOrders: renderAvailableOrders,
    fillMarketOrder: fillMarketOrder
  };

  G.fillMarketOrder = function (orderId) {
    return fillMarketOrder(orderId, G);
  };
})();
