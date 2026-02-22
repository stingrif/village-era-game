import { createApp } from 'vue';
import * as PIXI from 'pixi.js';
import axios from 'axios';

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) || '/api';
/** Белый список бота — не подставлять chat_id из БД (open redirect). */
const BOT_USERNAME = 'PHXPW';

/* ── Ассеты яиц с GitHub raw URL ── */
const EGG_BASE = 'https://raw.githubusercontent.com/PhoenixPaw/PhoenixPaw/main/%D1%8F%D0%B9%D1%86%D0%B0/';
const EGG_ASSET_MAP = {
  egg_red:    'красное.png',
  egg_blue:   'синие стандарт.png',
  egg_green:  'зеленое.png',
  egg_yellow: 'желтое.png',
  egg_purple: 'фиолетоое.png',   // опечатка в оригинале — оставляем as-is
  egg_black:  'теневое.png',
  egg_fire:   'огненное.png',
  egg_white:  'описание 4.png',  // временный placeholder
};

/* ── XP per level: формула роста ── */
const XP_FOR_LEVEL = (lvl) => {
  if (lvl <= 5)  return 1000;
  if (lvl <= 10) return 2000;
  if (lvl <= 20) return 5000;
  return 10000;
};

/* ── Названия классов по уровню ── */
const charClassByLevel = (lvl) => {
  if (lvl < 3)  return 'Новобранец';
  if (lvl < 6)  return 'Следопыт';
  if (lvl < 10) return 'Ветеран';
  if (lvl < 15) return 'Мастер деревни';
  if (lvl < 21) return 'Хранитель';
  return 'Легенда Тигрита';
};

/* ── Игровые ключевые слова для +5 XP ── */
const GAME_KEYWORDS = ['рейд', 'ярмарка', 'осада', 'стройка', 'квест', 'ивент', 'событие', 'бой', 'атака', 'поход'];

/* ── Маппинг папок ассетов ── */
const ITEM_FOLDER_MAP = {
  relic_slot:    'relics',
  buff:          'buffs',
  curse:         'curses',
  artifact_relic:'artifacts',
};

/* ── Mock-данные зон (Telegram-чаты с ботом = зоны мира) ── */
const MOCK_ZONES = [
  {
    id: 'zone_1', name: 'Деревня Тигрит', type: 'starter',
    players_online: 42, total_players: 156, xp_multiplier: 1.0,
    description: 'Главная зона мира — стартовая деревня проекта Phoenix',
    active: true, bot_code: 'zone_1',
    mapX: 50, mapY: 35,
  },
  {
    id: 'zone_2', name: 'Торговые ряды', type: 'starter',
    players_online: 18, total_players: 89, xp_multiplier: 1.2,
    description: 'Зона торговли. Бонус к XP за торговые темы',
    active: true, bot_code: 'zone_2',
    mapX: 30, mapY: 25,
  },
  {
    id: 'zone_3', name: 'Военный лагерь', type: 'starter',
    players_online: 31, total_players: 120, xp_multiplier: 1.5,
    description: 'Зона боя и рейдов. XP ×1.5 за военные сообщения',
    active: true, bot_code: 'zone_3',
    mapX: 70, mapY: 22,
  },
  {
    id: 'zone_4', name: 'Гильдия Северного Ветра', type: 'community',
    players_online: 8, total_players: 34, xp_multiplier: 1.0,
    description: 'Сообщество игроков. Подключили бота 3 дня назад',
    active: true, bot_code: 'zone_4',
    mapX: 20, mapY: 55,
  },
  {
    id: 'zone_5', name: 'Клан Железного Кулака', type: 'community',
    players_online: 5, total_players: 21, xp_multiplier: 1.0,
    description: 'Новая зона — подключена вчера',
    active: true, bot_code: 'zone_5',
    mapX: 75, mapY: 60,
  },
  {
    id: 'zone_6', name: 'Академия Магии', type: 'community',
    players_online: 12, total_players: 47, xp_multiplier: 1.2,
    description: 'Чат магов и алхимиков. Подключили бота неделю назад',
    active: true, bot_code: 'zone_6',
    mapX: 45, mapY: 70,
  },
];

/* Линии-связи между зонами для карты */
const ZONE_LINKS = [
  { id:'l1', from:'zone_1', to:'zone_2' },
  { id:'l2', from:'zone_1', to:'zone_3' },
  { id:'l3', from:'zone_1', to:'zone_4' },
  { id:'l4', from:'zone_1', to:'zone_5' },
  { id:'l5', from:'zone_1', to:'zone_6' },
  { id:'l6', from:'zone_2', to:'zone_4' },
  { id:'l7', from:'zone_3', to:'zone_5' },
];

/* ── Mock-данные (используются если API недоступен) ── */
const MOCK_VILLAGE = {
  name: 'Тигрит', level: 7, xp: 630, activity: 84,
  build_name: 'Рыночная площадь', build_progress: 63,
  resources: { wood: 340, stone: 120, gold: 890, food: 210, influence: 45 },
  population: 34, population_max: 50,
};

const MOCK_PLAYERS = [
  { id:1, username:'Aldric', race:'Human', clazz:'Warrior', xp:4820, level:12,
    job:'Страж', house:{ x:14, y:8, name:'Северный форпост' },
    friends_count:7, is_online:true, token_balance:1240 },
  { id:2, username:'Sylwen', race:'Elf', clazz:'Mage', xp:3910, level:10,
    job:'Алхимик', house:{ x:8, y:12, name:'Магическая башня' },
    friends_count:12, is_online:true, token_balance:880 },
  { id:3, username:'Borrin', race:'Dwarf', clazz:'Craftsman', xp:2840, level:8,
    job:'Кузнец', house:{ x:20, y:6, name:'Кузница' },
    friends_count:4, is_online:false, token_balance:3400 },
];

const MOCK_ACTIVE_EVENTS = [
  { id:'evt_1', name:'Рейд на Холмы Хаоса', type:'raid',
    end_ts: Date.now() + 8040000,
    description:'Орки атакуют северные рубежи', reward:'200 💎 + 3 редких ресурса', entry_cost: 10 },
  { id:'evt_2', name:'Осенняя Ярмарка', type:'market',
    end_ts: Date.now() + 172800000,
    description:'Торговые бонусы +25%', reward:'Титул торговца + 50 💎', entry_cost: 0 },
];

const MOCK_EVENTS = [
  { id:1, kind:'msg', ts: Date.now()-300000, payload:'Aldric: Кто идёт на рейд сегодня?' },
  { id:2, kind:'event', ts: Date.now()-600000, title:'Ярмарка', payload:'Начался торговый сезон' },
  { id:3, kind:'dialogue', ts: Date.now()-3600000, payload:'Старейшина: Деревня растёт. Скоро откроем новые земли.' },
  { id:4, kind:'external', ts: Date.now()-7200000, payload:'Завершён квест «Путь следопыта»' },
];

const MOCK_CHAT = [
  { id:1, author:'Aldric', ts: Date.now()-900000, text:'Кто идёт на рейд сегодня?', xp:3 },
  { id:2, author:'Sylwen', ts: Date.now()-840000, text:'@Aldric Я готов! Встречаемся у ворот', xp:4 },
  { id:3, author:'Borrin', ts: Date.now()-720000, text:'Нужно ещё 2 человека для рейда', xp:5 },
  { id:4, author:'Aldric', ts: Date.now()-600000, text:'Ресурсов хватает, выдвигаемся в полночь', xp:2 },
];

const MOCK_COMMANDS = [
  { cmd:'/start',   code:'start',   desc:'Главное меню бота',                type:'game',    token_cost:0 },
  { cmd:'/village', code:'village', desc:'Статус деревни, ресурсы, стройка', type:'game',    token_cost:0 },
  { cmd:'/me',      code:'me',      desc:'Твой профиль, уровень, XP, дом',   type:'game',    token_cost:0 },
  { cmd:'/top',     code:'top',     desc:'Топ игроков по XP',                type:'game',    token_cost:0 },
  { cmd:'/balance', code:'balance', desc:'Баланс PHOEX-токенов',              type:'game',    token_cost:0 },
  { cmd:'/map',     code:'map',     desc:'Карта деревни',                    type:'game',    token_cost:0 },
  { cmd:'/friends', code:'friends', desc:'Список друзей',                    type:'game',    token_cost:0 },
  { cmd:'/build',   code:'build',   desc:'Начать строительство',             type:'game',    token_cost:0 },
  { cmd:'/boost',   code:'boost',   desc:'Ускорить строительство за токены', type:'game',    token_cost:50 },
  { cmd:'/events',  code:'events',  desc:'Текущие ивенты деревни',           type:'game',    token_cost:0 },
  { cmd:'/admin',   code:'admin',   desc:'Панель управления (только админ)', type:'admin',   token_cost:0 },
];

/* ══════════════════════════════════════════════════════
   VUE-ПРИЛОЖЕНИЕ
   ══════════════════════════════════════════════════════ */
const app = createApp({
  data() {
    return {
      activeTab: 'village',

      /* Данные деревни */
      village: { ...MOCK_VILLAGE },
      mapData: null,
      mapLoading: false,

      /* Игроки */
      players: [...MOCK_PLAYERS],
      playersLoading: false,
      playerSort: 'xp',
      playerFilterRace: '',

      /* События */
      events: [...MOCK_EVENTS],
      activeEvents: [...MOCK_ACTIVE_EVENTS],
      journalFilter: '',

      /* Редактор */
      assets: { tiles: [], buildings: [], characters: [] },
      selectedAsset: { type: null, id: null, name: null },
      selectedTileProps: null,
      assetSections: { tiles: true, buildings: true, characters: true },
      editorTool: 'brush',
      cursorCoords: { x: 0, y: 0 },
      pixiApp: null,
      editorApp: null,
      editorMapData: null,

      /* Зоны открытого мира */
      zones: [...MOCK_ZONES],
      activeZoneId: MOCK_ZONES[0].id,
      zonesLoading: false,
      worldFilter: '',

      /* Каталог предметов (единый источник) */
      itemsCatalog: [],
      itemsLoading: false,
      itemsFilter: '',   // '' | 'relic_slot' | 'buff' | 'curse' | 'artifact_relic' | 'amulet' | 'egg'
      itemsRarityFilter: '',

      /* Чат и XP-прокачка */
      chatMessages: [...MOCK_CHAT],
      chatInput: '',
      chatFilter: '',
      chatXp: 0,       // XP в текущем уровне
      chatXpTotal: 0,   // Всего XP за всё время
      chatLevel: 1,
      totalMessages: MOCK_CHAT.filter(m => m.mine).length,

      /* XP-тост */
      xpToastVisible: false,
      xpToastText: '',

      /* Инструкция */
      showInstructions: false,
      instrTab: 'tigrit',

      /* Бот-команды */
      botCommands: [...MOCK_COMMANDS],

      /* API-статус */
      apiOnline: false,

      /* Уведомления */
      notifications: [],
      notifCounter: 0,
    };
  },

  computed: {
    /** Процент XP деревни */
    villageXpPercent() {
      const xp  = this.village.xp || 0;
      const cap = (this.village.level || 1) * 1000;
      return Math.min(100, Math.round(xp / cap * 100));
    },

    /** Список ресурсов для отображения */
    resourceList() {
      const r = this.village.resources || {};
      return [
        { key:'wood',      icon:'🪵', label:'Дерево',   value:r.wood      || 0, cls: this.resCls(r.wood      || 0, 500) },
        { key:'stone',     icon:'🪨', label:'Камень',   value:r.stone     || 0, cls: this.resCls(r.stone     || 0, 300) },
        { key:'gold',      icon:'🪙', label:'Монеты',   value:r.gold      || 0, cls: this.resCls(r.gold      || 0, 1000) },
        { key:'food',      icon:'🌾', label:'Еда',      value:r.food      || 0, cls: this.resCls(r.food      || 0, 400) },
        { key:'influence', icon:'🔮', label:'Влияние',  value:r.influence || 0, cls: this.resCls(r.influence || 0, 100) },
      ].filter(item => item.value > 0);
    },

    /** Процент населения */
    populationPercent() {
      if (!this.village.population_max) return 0;
      return Math.round(this.village.population / this.village.population_max * 100);
    },

    /** CSS-класс прогресс-бара населения */
    populationCls() {
      const p = this.populationPercent;
      if (p >= 90) return 'red';
      if (p >= 70) return '';
      return 'green';
    },

    /** Игроки с фильтром и сортировкой */
    filteredPlayers() {
      let list = [...this.players];
      if (this.playerFilterRace) list = list.filter(p => p.race === this.playerFilterRace);
      if (this.playerSort === 'xp')     list.sort((a, b) => (b.xp || 0) - (a.xp || 0));
      if (this.playerSort === 'level')  list.sort((a, b) => (b.level || 0) - (a.level || 0));
      if (this.playerSort === 'online') list.sort((a, b) => (b.is_online ? 1 : 0) - (a.is_online ? 1 : 0));
      return list;
    },

    /** Количество онлайн-игроков */
    onlinePlayers() {
      return this.players.filter(p => p.is_online).length;
    },

    /** Фильтрованный журнал событий */
    filteredJournal() {
      if (!this.journalFilter) return this.events;
      return this.events.filter(e => e.kind === this.journalFilter);
    },

    /** Фильтрованные чат-сообщения */
    filteredChatMessages() {
      if (!this.chatFilter) return this.chatMessages;
      if (this.chatFilter === 'question') return this.chatMessages.filter(m => m.text.includes('?'));
      if (this.chatFilter === 'quest') {
        const kw = GAME_KEYWORDS;
        return this.chatMessages.filter(m => kw.some(k => m.text.toLowerCase().includes(k)));
      }
      return this.chatMessages;
    },

    /** XP до следующего уровня */
    xpForNextLevel() {
      return XP_FOR_LEVEL(this.chatLevel);
    },

    /** Процент прогресса XP */
    xpProgressPercent() {
      return Math.min(100, Math.round(this.chatXp / this.xpForNextLevel * 100));
    },

    /** Название класса персонажа */
    charClassName() {
      return charClassByLevel(this.chatLevel);
    },

    /** Активная зона */
    activeZone() {
      return this.zones.find(z => z.id === this.activeZoneId) || null;
    },

    /** Зоны с фильтром */
    filteredZones() {
      if (!this.worldFilter) return this.zones;
      return this.zones.filter(z => z.type === this.worldFilter);
    },

    /** Количество активных зон */
    zonesOnline() {
      return this.zones.filter(z => z.players_online > 0).length;
    },

    /** Предметы с фильтрами по типу слота и редкости */
    filteredItems() {
      return this.itemsCatalog.filter(item => {
        if (this.itemsFilter && item.slot_type !== this.itemsFilter) return false;
        if (this.itemsRarityFilter && item.rarity !== this.itemsRarityFilter) return false;
        return true;
      });
    },

    /** Иконка-эмодзи по типу предмета */
    itemTypeEmoji() {
      return {
        relic_slot:     '✨',
        buff:           '🛡️',
        curse:          '🌑',
        artifact_relic: '🔮',
        amulet:         '💎',
        egg:            '🥚',
      };
    },

    /** Цвет редкости */
    rarityColor() {
      return {
        common:  '#aaa',
        rare:    '#6fa8dc',
        magic:   '#9b59b6',
        EPIC:    '#e74c3c',
        PREMIUM: '#ffd700',
        FIRE:    '#e84118',
        YIN:     '#74b9ff',
        YAN:     '#fd9644',
        TSY:     '#2ecc71',
        MAGIC:   '#9b59b6',
      };
    },

    /** Суммарное количество игроков во всех зонах */
    zonesTotalPlayers() {
      return this.zones.reduce((sum, z) => sum + z.total_players, 0);
    },

    /** Зона с наилучшим множителем XP */
    bestXpZone() {
      return [...this.zones].sort((a, b) => b.xp_multiplier - a.xp_multiplier)[0] || null;
    },

    /** Зоны с координатами для карты (mapX, mapY уже в данных) */
    zonesWithCoords() {
      return this.zones;
    },

    /** Линии-связи с координатами для SVG */
    zoneLinks() {
      return ZONE_LINKS.map(link => {
        const from = this.zones.find(z => z.id === link.from);
        const to   = this.zones.find(z => z.id === link.to);
        if (!from || !to) return null;
        return {
          id:     link.id,
          x1:     from.mapX,
          y1:     from.mapY,
          x2:     to.mapX,
          y2:     to.mapY,
          active: this.activeZoneId === link.from || this.activeZoneId === link.to,
        };
      }).filter(Boolean);
    },

    /** Топ по количеству XP в чате */
    chatTopPlayers() {
      const map = {};
      this.chatMessages.forEach(m => {
        if (!map[m.author]) map[m.author] = { author: m.author, totalXp: 0 };
        map[m.author].totalXp += m.xp || 0;
      });
      return Object.values(map).sort((a, b) => b.totalXp - a.totalXp).slice(0, 5);
    },
  },

  mounted() {
    this.loadFromLocalStorage();
    this.fetchVillageData();
    this.fetchPlayers();
    this.fetchEvents();
    this.fetchActiveEvents();
    this.fetchAssets();
    this.fetchZones();
    this.fetchItemsCatalog();
    this.checkApiHealth();

    setInterval(() => this.checkApiHealth(), 30000);
    setInterval(() => { this.fetchVillageData(); this.fetchEvents(); this.fetchActiveEvents(); }, 10000);

    /* При переключении вкладок — инициализировать PIXI */
    this.$watch('activeTab', (newTab) => {
      if (newTab === 'village' && !this.pixiApp) {
        this.$nextTick(() => this.initializeMap('map-container'));
      }
      if (newTab === 'editor') {
        this.$nextTick(() => this.initializeEditor('editor-canvas'));
      }
      if (newTab === 'chat') {
        this.$nextTick(() => this.scrollChatToBottom());
      }
    });
  },

  methods: {

    /* ── API ── */

    async fetchVillageData() {
      try {
        const r = await axios.get(`${API_URL}/village`);
        if (r.data) this.village = { ...MOCK_VILLAGE, ...r.data };
      } catch { /* fallback к mock уже в data() */ }
    },

    async fetchPlayers() {
      this.playersLoading = true;
      try {
        const r = await axios.get(`${API_URL}/users`, { params: { limit: 50 } });
        if (r.data?.length) this.players = r.data;
      } catch { /* fallback к mock */ }
      finally { this.playersLoading = false; }
    },

    async fetchEvents() {
      try {
        const r = await axios.get(`${API_URL}/events`);
        if (r.data?.length) this.events = r.data;
      } catch {}
    },

    async fetchActiveEvents() {
      try {
        const r = await axios.get(`${API_URL}/events/active`);
        if (r.data?.length) this.activeEvents = r.data;
      } catch {}
    },

    async fetchAssets() {
      try {
        const r = await axios.get(`${API_URL}/assets`);
        if (r.data) this.assets = r.data;
      } catch {}
    },

    async fetchZones() {
      this.zonesLoading = true;
      try {
        /* Пробуем /api/zones, затем /api/chats */
        let r = await axios.get(`${API_URL}/zones`).catch(() => null);
        if (!r?.data?.length) r = await axios.get(`${API_URL}/chats`).catch(() => null);
        if (r?.data?.length) {
          /* Дополняем серверные данные координатами карты из mock если их нет */
          this.zones = r.data.map((z, i) => ({
            mapX: MOCK_ZONES[i]?.mapX ?? Math.round(15 + Math.random() * 70),
            mapY: MOCK_ZONES[i]?.mapY ?? Math.round(15 + Math.random() * 70),
            ...z,
          }));
          if (!this.activeZoneId) this.activeZoneId = this.zones[0]?.id || null;
        }
      } catch { /* fallback: mock-данные уже в data() */ }
      finally { this.zonesLoading = false; }
    },

    /**
     * Форматирует числовое значение стата предмета для отображения.
     * Числа < 1 выводятся как проценты, целые — как есть.
     */
    formatStat(key, val) {
      const prefix = (typeof val === 'number' && val > 0) ? '+' : '';
      if (typeof val === 'number' && val !== 0 && Math.abs(val) < 1) {
        return `${key}: ${prefix}${(val * 100).toFixed(0)}%`;
      }
      return `${key}: ${prefix}${val}`;
    },

    /** Загрузить единый каталог предметов с API */
    async fetchItemsCatalog() {
      this.itemsLoading = true;
      try {
        const { data } = await axios.get(`${API_URL}/items-catalog`);
        this.itemsCatalog = Array.isArray(data) ? data : (data.items ?? []);
      } catch {
        /* fallback — пустой каталог, пользователь увидит placeholder */
        this.itemsCatalog = [];
      } finally {
        this.itemsLoading = false;
      }
    },

    async checkApiHealth() {
      try {
        await axios.get(`${API_URL}/health`, { timeout: 5000 });
        this.apiOnline = true;
      } catch {
        this.apiOnline = false;
      }
    },

    /* ── Форматирование ── */

    /** Форматирует unix timestamp (сек или мс) или ISO-строку. */
    formatTime(ts) {
      if (ts == null) return '—';
      const d = typeof ts === 'number' ? new Date(ts > 1e12 ? ts : ts * 1000) : new Date(ts);
      return isNaN(d.getTime()) ? String(ts) : d.toLocaleTimeString('ru', { hour:'2-digit', minute:'2-digit' });
    },

    /** Относительное время: «5 мин назад», «2 ч назад». */
    formatRelative(ts) {
      if (ts == null) return '—';
      const d = typeof ts === 'number' ? new Date(ts > 1e12 ? ts : ts * 1000) : new Date(ts);
      if (isNaN(d.getTime())) return String(ts);
      const diff = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diff < 60)  return `${diff}с назад`;
      if (diff < 3600) return `${Math.floor(diff/60)}мин назад`;
      if (diff < 86400) return `${Math.floor(diff/3600)}ч назад`;
      return `${Math.floor(diff/86400)}д назад`;
    },

    /** Обратный отсчёт до end_ts (unix мс). */
    formatCountdown(endTs) {
      const ms  = endTs - Date.now();
      if (ms <= 0) return 'Завершено';
      const h  = Math.floor(ms / 3600000);
      const m  = Math.floor((ms % 3600000) / 60000);
      const s  = Math.floor((ms % 60000) / 1000);
      if (h > 0) return `${h}ч ${m}мин`;
      return `${m}мин ${s}с`;
    },

    /** Обрезает строку до maxLen символов. */
    truncate(str, maxLen) {
      if (!str) return '';
      return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
    },

    /* ── Типы событий ── */

    getEventType(kind) {
      return { msg:'Сообщение', event:'Событие', dialogue:'Диалог', external:'Внешнее', raid:'Рейд', market:'Ярмарка', quest:'Квест', siege:'Осада', build:'Стройка' }[kind] || kind || '—';
    },

    getEventTypeLabel(type) {
      return { raid:'⚔ РЕЙД', market:'🏪 ЯРМАРКА', quest:'📜 КВЕСТ', siege:'🏰 ОСАДА', build:'🔨 СТРОЙКА', dialogue:'💬 ДИАЛОГ', external:'🔗 ВНЕШНЕЕ', event:'⚡ СОБЫТИЕ' }[type] || type || '?';
    },

    eventIcon(kind) {
      return { msg:'💬', event:'⚡', dialogue:'🗣', external:'🔗', raid:'⚔', market:'🏪', quest:'📜', siege:'🏰' }[kind] || '•';
    },

    eventBadgeClass(type) {
      return { raid:'badge-raid', market:'badge-market', quest:'badge-teal', external:'badge-paid' }[type] || 'badge-service';
    },

    /* ── Игроки ── */

    playerColor(player) {
      let hash = 0;
      const name = player.username || 'anon';
      for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
      const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
      return `#${'000000'.slice(c.length)}${c}`;
    },

    playerXpPercent(player) {
      const xp  = player.xp || 0;
      const cap = (player.level || 1) * 1000;
      return Math.min(100, Math.round(xp / cap * 100));
    },

    rankClass(idx) {
      if (idx === 0) return 'gold';
      if (idx === 1) return 'silver';
      if (idx === 2) return 'bronze';
      return '';
    },

    openPlayerProfile(player) {
      this.notify(`${player.username} — Ур.${player.level || 1}, ${player.xp || 0} XP`);
    },

    resCls(val, cap) {
      const p = val / cap;
      if (p >= 0.7)  return 'high';
      if (p >= 0.3)  return 'med';
      return 'low';
    },

    /* ── Команды ── */

    cmdBadgeClass(type) {
      return { game:'badge-game', admin:'badge-admin', service:'badge-service', paid:'badge-paid' }[type] || 'badge-game';
    },

    copyCommand(cmd) {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(cmd).then(() => this.notify(`Скопировано: ${cmd}`));
      } else {
        this.notify(cmd);
      }
    },

    /* ── Зоны ── */

    /**
     * Выбирает активную зону (переключает чат).
     * @param {string} zoneId
     */
    selectZone(zoneId) {
      this.activeZoneId = zoneId;
      /* Загружаем сообщения зоны если endpoint есть */
      this.fetchZoneMessages(zoneId);
    },

    /** Загружает сообщения конкретной зоны. */
    async fetchZoneMessages(zoneId) {
      try {
        const r = await axios.get(`${API_URL}/zones/${zoneId}/messages`);
        if (r.data?.length) this.chatMessages = r.data;
      } catch { /* оставляем текущие mock-сообщения */ }
    },

    /**
     * Ссылка для перехода в зону через бота.
     * @param {object} zone
     * @returns {string}
     */
    joinZoneLink(zone) {
      return `https://t.me/${BOT_USERNAME}?start=zone_${zone.bot_code || zone.id}`;
    },

    /** При смене зоны через дропдаун в чате — загружаем сообщения */
    onZoneChange() {
      if (this.activeZoneId) this.fetchZoneMessages(this.activeZoneId);
      this.$nextTick(() => this.scrollChatToBottom());
    },

    /**
     * CSS-класс для отображения множителя XP.
     * @param {number} mult
     * @returns {string}
     */
    xpMultClass(mult) {
      if (mult >= 2.0) return 'x2';
      if (mult >= 1.5) return 'x1_5';
      if (mult >= 1.2) return 'x1_2';
      return 'x1';
    },

    /* ── Инструкция ── */

    openInstructions() {
      this.instrTab = 'tigrit';
      this.showInstructions = true;
    },

    /* ── XP-механика (Общение) ── */

    /**
     * Вычисляет количество XP за сообщение с учётом множителя зоны.
     * Базовые значения: обычное=2, вопрос=3, ответ=4, игровая тема=5.
     * @param {string} text
     * @returns {number}
     */
    calcXp(text) {
      if (!text?.trim()) return 0;
      const lower = text.toLowerCase();
      let base = 2;
      if (GAME_KEYWORDS.some(kw => lower.includes(kw))) base = 5;
      else if (text.trim().startsWith('@'))             base = 4;
      else if (text.includes('?'))                     base = 3;

      const zone = this.zones.find(z => z.id === this.activeZoneId);
      return Math.round(base * (zone?.xp_multiplier || 1.0));
    },

    /** Подпись для кнопки «Отправить +N XP» */
    calcXpLabel(text) {
      const xp = this.calcXp(text);
      return xp ? `+${xp} XP` : '';
    },

    /** Отправляет сообщение в чат, начисляет XP. */
    async sendChatMessage() {
      const text = this.chatInput.trim();
      if (!text) return;

      const xp = this.calcXp(text);
      const msg = {
        id:     Date.now(),
        author: 'Я',
        ts:     Date.now(),
        text,
        xp,
        mine:   true,
      };

      this.chatMessages.push(msg);
      this.chatInput = '';
      this.totalMessages++;
      this.applyXp(xp);
      this.saveToLocalStorage();
      this.$nextTick(() => this.scrollChatToBottom());

      /* POST на сервер (если endpoint существует) */
      try {
        await axios.post(`${API_URL}/chat/message`, {
          text,
          xp,
          zone_id: this.activeZoneId,
        });
      } catch { /* backend необязателен */ }
    },

    /**
     * Начисляет XP, повышает уровень при достижении порога.
     * @param {number} xp
     */
    applyXp(xp) {
      this.chatXp      += xp;
      this.chatXpTotal += xp;
      this.showXpToast(`+${xp} XP за сообщение`);

      while (this.chatXp >= this.xpForNextLevel) {
        this.chatXp -= this.xpForNextLevel;
        this.chatLevel++;
        this.notify(`🎉 Ур. ${this.chatLevel} — ${this.charClassName}!`);
      }
    },

    /** Показывает toast-уведомление о полученном XP. */
    showXpToast(text) {
      this.xpToastText    = text;
      this.xpToastVisible = true;
      setTimeout(() => { this.xpToastVisible = false; }, 2000);
    },

    /** Добавляет уведомление в очередь. */
    notify(text) {
      const id = ++this.notifCounter;
      this.notifications.push({ id, text });
      setTimeout(() => {
        this.notifications = this.notifications.filter(n => n.id !== id);
      }, 3500);
    },

    /** Прокручивает чат вниз. */
    scrollChatToBottom() {
      const el = this.$refs.chatMessages;
      if (el) el.scrollTop = el.scrollHeight;
    },

    /* ── Персистентность XP ── */

    saveToLocalStorage() {
      try {
        localStorage.setItem('tigrit_chat', JSON.stringify({
          chatXp:       this.chatXp,
          chatXpTotal:  this.chatXpTotal,
          chatLevel:    this.chatLevel,
          totalMessages:this.totalMessages,
        }));
      } catch {}
    },

    loadFromLocalStorage() {
      try {
        const raw = localStorage.getItem('tigrit_chat');
        if (!raw) return;
        const data = JSON.parse(raw);
        this.chatXp        = data.chatXp        || 0;
        this.chatXpTotal   = data.chatXpTotal   || 0;
        this.chatLevel     = data.chatLevel     || 1;
        this.totalMessages = data.totalMessages || 0;
      } catch {}
    },

    /* ── Резолверы ассетов ── */

    /**
     * URL PNG-иконки яйца с GitHub.
     * @param {string} key — ключ из каталога (egg_red, egg_blue...)
     * @returns {string|null}
     */
    resolveEggAsset(key) {
      const file = EGG_ASSET_MAP[key];
      if (!file) return null;
      return EGG_BASE + encodeURIComponent(file);
    },

    /**
     * URL иконки предмета из папки public/assets/items/.
     * @param {string} key — ID предмета
     * @param {string} slotType — slot_type из каталога
     * @returns {string}
     */
    resolveItemAsset(key, slotType) {
      const folder = ITEM_FOLDER_MAP[slotType] || 'relics';
      return `/assets/items/${folder}/${key}.png`;
    },

    /** Цвет placeholder-квадрата по редкости предмета. */
    rarityPlaceholderClass(rarity) {
      const map = { common:'rarity-common', rare:'rarity-rare', magic:'rarity-magic', epic:'rarity-epic', PREMIUM:'rarity-PREMIUM' };
      return `item-placeholder ${map[rarity] || 'rarity-common'}`;
    },

    /* ── Редактор ── */

    selectAsset(type, asset) {
      const id   = typeof asset === 'object' ? (asset.id || asset) : asset;
      const name = typeof asset === 'object' ? (asset.name || asset.id) : asset;
      this.selectedAsset = { type, id, name };
    },

    getColorForTileType(type) {
      if (type === 'center') return 0xd3b17d;
      const b = (this.assets.buildings || []).find(x => (x.id || x) === type);
      if (b?.color) return parseInt(String(b.color).replace('#',''), 16);
      const t = (this.assets.tiles || []).find(x => (x.id || x) === type);
      if (t?.color) return parseInt(String(t.color).replace('#',''), 16);
      return 0x3d3320;
    },

    initializeMap(containerId) {
      const container = document.getElementById(containerId);
      if (!container || this.pixiApp) return;
      this.mapLoading = true;

      this.pixiApp = new PIXI.Application({
        width:           container.offsetWidth  || 640,
        height:          container.offsetHeight || 480,
        backgroundColor: 0x1a1610,
        antialias:       true,
        resizeTo:        container,
      });
      container.appendChild(this.pixiApp.view);

      axios.get(`${API_URL}/map`).then(r => {
        this.mapData = r.data;
        this.renderMap();
      }).catch(() => {
        this.renderFallbackMap();
      }).finally(() => { this.mapLoading = false; });
    },

    renderMap() {
      if (!this.pixiApp || !this.mapData) return;
      const cont  = new PIXI.Container();
      const tileW = 64, tileH = 32;

      (this.mapData.tiles || []).forEach(tile => {
        const color = this.getColorForTileType(tile.type);
        const g = new PIXI.Graphics();
        g.beginFill(color, 0.85);
        /* изометрический ромб */
        g.drawPolygon([
          tileW/2, 0,
          tileW,   tileH/2,
          tileW/2, tileH,
          0,       tileH/2,
        ]);
        g.endFill();
        g.x = (tile.x - tile.y) * tileW/2;
        g.y = (tile.x + tile.y) * tileH/2;
        cont.addChild(g);
      });

      cont.x = this.pixiApp.screen.width  / 2;
      cont.y = 40;
      this.pixiApp.stage.addChild(cont);
    },

    /** Рисует заглушку карты когда API недоступен. */
    renderFallbackMap() {
      if (!this.pixiApp) return;
      const g = new PIXI.Graphics();
      g.beginFill(0x2e2618);
      g.drawRect(0, 0, this.pixiApp.screen.width, this.pixiApp.screen.height);
      g.endFill();
      const text = new PIXI.Text('Карта недоступна', { fontSize:16, fill:0x9a8a6a });
      text.x = this.pixiApp.screen.width  / 2 - text.width  / 2;
      text.y = this.pixiApp.screen.height / 2 - text.height / 2;
      this.pixiApp.stage.addChild(g, text);
    },

    initializeEditor(containerId) {
      const container = document.getElementById(containerId);
      if (!container) return;

      if (this.editorApp) {
        if (!container.contains(this.editorApp.view)) container.appendChild(this.editorApp.view);
        return;
      }

      this.editorApp = new PIXI.Application({
        width:           container.offsetWidth  || 640,
        height:          container.offsetHeight || 480,
        backgroundColor: 0x1a1610,
        antialias:       true,
        resizeTo:        container,
      });
      container.appendChild(this.editorApp.view);

      axios.get(`${API_URL}/map`).then(r => {
        this.editorMapData = JSON.parse(JSON.stringify(r.data));
        this.renderEditorMap();
      }).catch(() => this.renderEditorGrid());
    },

    renderEditorGrid() {
      if (!this.editorApp) return;
      const cont   = new PIXI.Container();
      const tileW  = 64, tileH = 32, cols = 16, rows = 16;

      for (let x = 0; x < cols; x++) {
        for (let y = 0; y < rows; y++) {
          const g = new PIXI.Graphics();
          g.lineStyle(1, 0x3d3320, 0.6);
          g.beginFill(0x2e2618);
          g.drawPolygon([ tileW/2,0, tileW,tileH/2, tileW/2,tileH, 0,tileH/2 ]);
          g.endFill();
          g.x = (x - y) * tileW/2;
          g.y = (x + y) * tileH/2;
          g.eventMode = 'static';
          g.cursor = 'pointer';
          g.on('pointerdown', () => this.placeTile(x, y));
          g.on('pointermove', () => { this.cursorCoords = { x, y }; });
          cont.addChild(g);
        }
      }

      cont.x = this.editorApp.screen.width / 2;
      cont.y = 40;
      this.editorApp.stage.addChild(cont);
    },

    renderEditorMap() {
      if (!this.editorApp || !this.editorMapData) return;
      this.renderEditorGrid();
    },

    placeTile(x, y) {
      if (!this.selectedAsset.type) { this.notify('Выберите ассет из панели слева'); return; }
      if (!this.editorMapData) this.editorMapData = { tiles: [], width: 16, height: 16 };
      const idx = this.editorMapData.tiles.findIndex(t => t.x === x && t.y === y);
      if (idx !== -1) this.editorMapData.tiles.splice(idx, 1);
      this.editorMapData.tiles.push({ x, y, type: this.selectedAsset.id, name: this.selectedAsset.name });
      this.selectedTileProps = { x, y, type: this.selectedAsset.id, name: this.selectedAsset.name };
    },

    async saveMap() {
      if (!this.editorMapData) { this.notify('Нечего сохранять'); return; }
      try {
        /* PUT /api/map — стандартный endpoint редактора карты */
        await axios.put(`${API_URL}/map`, this.editorMapData, {
          headers: { 'X-API-Key': localStorage.getItem('editor_api_key') || '' }
        });
        this.notify('✅ Карта сохранена');
      } catch (e) {
        if (e.response?.status === 401) this.notify('❌ Нет прав: укажи Editor API Key в настройках');
        else this.notify('Ошибка сохранения — проверь подключение');
      }
    },

    exportMap() {
      if (!this.editorMapData) { this.notify('Нет данных карты'); return; }
      const blob = new Blob([JSON.stringify(this.editorMapData, null, 2)], { type:'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'tigrit_map.json';
      a.click();
    },

    importMap() {
      document.getElementById('import-map')?.click();
    },

    handleImport(e) {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          this.editorMapData = JSON.parse(ev.target.result);
          this.renderEditorMap();
          this.notify('✅ Карта импортирована');
        } catch { this.notify('Ошибка чтения файла'); }
      };
      reader.readAsText(file);
    },

    editorZoom(factor) {
      if (!this.editorApp) return;
      const stage = this.editorApp.stage;
      stage.scale.set(Math.min(3, Math.max(0.5, stage.scale.x * factor)));
    },
  },
});

app.mount('#app');
