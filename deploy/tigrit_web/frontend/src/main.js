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
      currentUserId: Number(localStorage.getItem('tigrit_user_id') || 1),
      homeZoneId: null,
      characterState: 'alive',
      trustScore: 50,
      playerBase: null,
      allBases: [],
      locations: [],
      locationsLoading: false,
      travelCurrent: null,
      travelTimer: null,
      selectedLocationId: null,
      locationLootLast: null,
      clanInfo: null,
      clanCreateName: '',
      clanCreateZoneId: 'zone_1',
      clanTargetId: null,
      clanContributeAmount: 10,
      raidTargetUserId: null,
      raidCombatId: null,

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

      /* ──────── Режим вида ────────
         viewModeTest: true  — кнопка видна всем (тест-режим).
         После подключения подписки: установить viewModeTest = false
         и вместо него читать this.hasSubscription из профиля. */
      viewMode: 'top',        // 'top' | 'third'
      viewModeTest: true,
      hasSubscription: false,

      /* ──────── Персонаж (3-е лицо) ──────── */
      playerChar: { tileX: 15, tileY: 15, moving: false, dir: 'S', anim: 'idle' },
      playerHP: 100, playerMaxHP: 100,
      playerMana: 50, playerMaxMana: 50,
      skills: [
        { id:'attack', name:'Атака',   key:'Q', cd:0, maxCd:2,  icon:'⚔️' },
        { id:'heal',   name:'Лечение', key:'E', cd:0, maxCd:8,  icon:'💚' },
        { id:'dash',   name:'Рывок',   key:'R', cd:0, maxCd:5,  icon:'💨' },
      ],
      combatLog: [],
      pixiWorldContainer: null,
      pixiCharSprite: null,

      /* ──────── Редактор карты ──────── */
      editorApiKey: '',
      editorSaving: false,

      /* ──────── Статус API деревни ──────── */
      villageApiError: false,

      /* ──────── Админ-панель Тигрит ──────── */
      adminApiKey: '',
      adminMsg: '',
      adminMsgOk: true,
      adminLoading: false,
      adminStatus: null,          // результат GET /api/admin/status
      _adminVillageLoaded: false,  // guard — загружены ли реальные данные
      _adminLoadingInProgress: false, // debounce двойной загрузки
      adminVillage: {
        name: 'Тигрит', level: 1, xp: 0, activity: 0,
        population: 0, population_max: 50,
        build_name: '', build_progress: 0,
        resources: { wood:0, stone:0, gold:0, food:0, influence:0 },
      },
      adminUser: { userId: null, xp: 0, level: 1, race: '', clazz: '' },
      adminUserSearch: '',
      adminUserResults: [],
      adminUserInfo: null,   // текущие данные выбранного игрока
      _userSearchTimer: null,
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

    /** Базы игроков на карте мира */
    basesWithCoords() {
      return (this.allBases || []).filter(b => Number.isFinite(Number(b.map_x)) && Number.isFinite(Number(b.map_y)));
    },

    /** Локации survival на карте мира */
    locationsWithCoords() {
      return (this.locations || []).filter(l => Number.isFinite(Number(l.mapX ?? l.map_x)) && Number.isFinite(Number(l.mapY ?? l.map_y)));
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
    this.fetchLocations();
    this.fetchBases();
    this.fetchSurvivalStatus();
    this.fetchTravelCurrent();
    this.fetchItemsCatalog();
    this.checkApiHealth();

    /* Загружаем ключи из localStorage */
    this.editorApiKey = localStorage.getItem('editor_api_key') || '';
    this.adminApiKey  = localStorage.getItem('tigrit_admin_key') || '';

    /* WASD / горячие клавиши для режима 3-го лица */
    this._onKeyDown = (e) => this.handleGameKey(e);
    window.addEventListener('keydown', this._onKeyDown);

    setInterval(() => this.checkApiHealth(), 30000);
    setInterval(() => { this.fetchVillageData(); this.fetchEvents(); this.fetchActiveEvents(); }, 10000);
    this.travelTimer = setInterval(() => this.fetchTravelCurrent(), 5000);

    /* При первой загрузке инициализируем карту если активна вкладка village */
    this.$nextTick(() => {
      if (this.activeTab === 'village') this.initVillageScene('map-container');
    });

    /* Мана восстанавливается в 3-м лице */
    setInterval(() => {
      if (this.viewMode === 'third') {
        this.playerMana = Math.min(this.playerMaxMana, this.playerMana + 5);
      }
    }, 3000);

    /* При переключении вкладок — инициализировать PIXI, автозагрузка в Админ */
    this.$watch('activeTab', (newTab) => {
      if (newTab === 'village') {
        this.$nextTick(() => this.initVillageScene('map-container'));
      }
      if (newTab === 'editor') {
        this.$nextTick(() => this.initializeEditor('editor-canvas'));
      }
      if (newTab === 'chat') {
        this.$nextTick(() => this.scrollChatToBottom());
      }
      if (newTab === 'admin') {
        this.$nextTick(() => this.adminOpenTab());
      }
      if (newTab === 'players') {
        this.$nextTick(() => this.fetchPlayers());
      }
    });

    /* Следим за сменой режима вида — перерисовываем сцену */
    this.$watch('viewMode', () => {
      if (this.activeTab === 'village') {
        this.$nextTick(() => this.initVillageScene('map-container'));
      }
    });
  },

  unmounted() {
    if (this._onKeyDown) window.removeEventListener('keydown', this._onKeyDown);
    if (this.travelTimer) clearInterval(this.travelTimer);
  },

  methods: {

    /* ── API ── */

    async fetchVillageData() {
      try {
        const r = await axios.get(`${API_URL}/village`);
        if (r.data) {
          this.village = { ...MOCK_VILLAGE, ...r.data };
          this.villageApiError = false;
          /* Кэш — восстановим при следующем старте если API недоступен */
          try { localStorage.setItem('tigrit_last_village', JSON.stringify(this.village)); } catch {}
        }
      } catch (e) {
        this.villageApiError = true;
        /* Восстанавливаем из кэша если первый раз */
        if (JSON.stringify(this.village) === JSON.stringify(MOCK_VILLAGE)) {
          try {
            const cached = localStorage.getItem('tigrit_last_village');
            if (cached) this.village = JSON.parse(cached);
          } catch {}
        }
      }
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
        /* Приоритет: survival/zones, затем /zones, затем /chats */
        let r = await axios.get(`${API_URL}/survival/zones`).catch(() => null);
        if (!r?.data?.length) r = await axios.get(`${API_URL}/zones`).catch(() => null);
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

    apiHeaders() {
      return { 'X-User-Id': String(this.currentUserId || 1) };
    },

    async fetchSurvivalStatus() {
      try {
        const r = await axios.get(`${API_URL}/survival/player/status`, { headers: this.apiHeaders() });
        const data = r.data || {};
        this.homeZoneId = data.home_zone_id || null;
        this.characterState = data.character_state || 'alive';
        this.trustScore = Number(data.trust_score ?? 50);
        this.playerBase = (data.base_x != null && data.base_y != null)
          ? { map_x: data.base_x, map_y: data.base_y, base_level: data.base_level, base_name: data.base_name, user_id: this.currentUserId }
          : null;
      } catch {}
    },

    async bindHomeZone(zoneId) {
      try {
        const payload = { zone_id: zoneId, user_id: this.currentUserId, tg_user_id: this.currentUserId };
        const r = await axios.post(`${API_URL}/survival/zone/bind`, payload, { headers: this.apiHeaders() });
        if (r.data?.ok) {
          this.homeZoneId = zoneId;
          await this.fetchSurvivalStatus();
          await this.fetchBases();
          this.notify('🏕️ Домашняя зона установлена');
        }
      } catch (e) {
        const msg = e?.response?.data?.detail?.error || e?.response?.data?.detail || 'Не удалось привязать зону';
        this.notify(`❌ ${msg}`);
      }
    },

    async changeHomeZone(zoneId) {
      try {
        const r = await axios.post(
          `${API_URL}/survival/zone/change`,
          { zone_id: zoneId, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.homeZoneId = zoneId;
          this.notify(`🔁 Домашняя зона сменена (−${r.data.price} PHOEX)`);
          await this.fetchSurvivalStatus();
        }
      } catch (e) {
        const msg = e?.response?.data?.detail || 'Не удалось сменить зону';
        this.notify(`❌ ${typeof msg === 'string' ? msg : 'Ошибка API'}`);
      }
    },

    async fetchLocations() {
      this.locationsLoading = true;
      try {
        const r = await axios.get(`${API_URL}/survival/locations`);
        if (Array.isArray(r.data)) this.locations = r.data;
      } catch {}
      finally { this.locationsLoading = false; }
    },

    async fetchBases() {
      try {
        const r = await axios.get(`${API_URL}/survival/bases`);
        if (Array.isArray(r.data)) this.allBases = r.data;
      } catch {}
    },

    async fetchTravelCurrent() {
      try {
        const r = await axios.get(`${API_URL}/survival/travel/current`, { headers: this.apiHeaders() });
        if (r.data?.travel === null) this.travelCurrent = null;
        else if (r.data?.id) this.travelCurrent = r.data;
      } catch {}
    },

    travelProgressPercent() {
      if (!this.travelCurrent?.start_ts || !this.travelCurrent?.arrive_ts) return 0;
      const start = new Date(this.travelCurrent.start_ts).getTime();
      const end = new Date(this.travelCurrent.arrive_ts).getTime();
      const now = Date.now();
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
      return Math.max(0, Math.min(100, Math.round(((now - start) / (end - start)) * 100)));
    },

    canArriveTravel() {
      if (!this.travelCurrent?.arrive_ts) return false;
      return Date.now() >= new Date(this.travelCurrent.arrive_ts).getTime();
    },

    async startTravel(locationId) {
      try {
        const r = await axios.post(
          `${API_URL}/survival/travel/start`,
          { to_id: locationId, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.selectedLocationId = locationId;
          this.notify('🧭 Путешествие началось');
          await this.fetchTravelCurrent();
        }
      } catch (e) {
        const msg = e?.response?.data?.detail || 'Не удалось начать путешествие';
        this.notify(`❌ ${typeof msg === 'string' ? msg : 'Ошибка API'}`);
      }
    },

    async arriveTravel() {
      if (!this.travelCurrent?.id) return;
      try {
        const r = await axios.post(
          `${API_URL}/survival/travel/arrive`,
          { travel_id: this.travelCurrent.id, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.selectedLocationId = r.data.location_id;
          this.notify(`📍 Прибытие: ${r.data.location_id}`);
          await this.fetchTravelCurrent();
        }
      } catch (e) {
        const msg = e?.response?.data?.detail || 'Не удалось подтвердить прибытие';
        this.notify(`❌ ${typeof msg === 'string' ? msg : 'Ошибка API'}`);
      }
    },

    async lootCurrentLocation() {
      if (!this.selectedLocationId) return;
      try {
        const r = await axios.post(
          `${API_URL}/survival/location/loot`,
          { location_id: this.selectedLocationId, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        this.locationLootLast = r.data;
        this.notify(`🎁 Лут: ${r.data.item_key} ×${r.data.qty}`);
      } catch (e) {
        const msg = e?.response?.data?.detail || 'Не удалось получить лут';
        this.notify(`❌ ${typeof msg === 'string' ? msg : 'Ошибка API'}`);
      }
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

    async createClan() {
      if (!this.clanCreateName?.trim()) {
        this.notify('❌ Введите название клана');
        return;
      }
      try {
        const r = await axios.post(
          `${API_URL}/survival/clan/create`,
          {
            clan_name: this.clanCreateName.trim(),
            zone_id: this.clanCreateZoneId || this.activeZoneId || 'zone_1',
            user_id: this.currentUserId,
          },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.notify(`🏰 Клан создан #${r.data.clan_id}`);
          this.clanTargetId = r.data.clan_id;
          await this.fetchClanInfo();
          await this.fetchSurvivalStatus();
        }
      } catch (e) {
        this.notify(`❌ ${e?.response?.data?.detail || 'Не удалось создать клан'}`);
      }
    },

    async joinClan(clanId = null) {
      const target = Number(clanId || this.clanTargetId);
      if (!target) return this.notify('❌ Укажите clan_id');
      try {
        const r = await axios.post(
          `${API_URL}/survival/clan/join`,
          { clan_id: target, user_id: this.currentUserId, tg_user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.notify('✅ Вступление в клан выполнено');
          this.clanTargetId = target;
          await this.fetchClanInfo();
          await this.fetchSurvivalStatus();
        }
      } catch (e) {
        this.notify(`❌ ${e?.response?.data?.detail || 'Не удалось вступить в клан'}`);
      }
    },

    async clanContribute() {
      const clanId = Number(this.clanTargetId);
      const amount = Number(this.clanContributeAmount || 0);
      if (!clanId || amount <= 0) return this.notify('❌ Укажите clan_id и сумму');
      try {
        const r = await axios.post(
          `${API_URL}/survival/clan/contribute`,
          { clan_id: clanId, amount, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.notify(`💰 Вклад в клан: ${amount}`);
          await this.fetchClanInfo();
        }
      } catch (e) {
        this.notify(`❌ ${e?.response?.data?.detail || 'Не удалось внести вклад'}`);
      }
    },

    async clanBetray() {
      const clanId = Number(this.clanTargetId);
      if (!clanId) return this.notify('❌ Укажите clan_id');
      try {
        const r = await axios.post(
          `${API_URL}/survival/clan/betray`,
          { clan_id: clanId, percent: 20, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (r.data?.ok) {
          this.notify(`🗡️ Предательство: украдено ${r.data.stolen} PHOEX`);
          await this.fetchClanInfo();
          await this.fetchSurvivalStatus();
        }
      } catch (e) {
        this.notify(`❌ ${e?.response?.data?.detail || 'Предательство не удалось'}`);
      }
    },

    async fetchClanInfo(clanId = null) {
      const target = Number(clanId || this.clanTargetId);
      if (!target) return;
      try {
        const r = await axios.get(`${API_URL}/survival/clan/${target}`);
        this.clanInfo = r.data;
      } catch {}
    },

    async startRaid() {
      const defenderId = Number(this.raidTargetUserId);
      if (!defenderId) return this.notify('❌ Укажите user_id цели для рейда');
      try {
        const start = await axios.post(
          `${API_URL}/survival/combat/start`,
          { defender_id: defenderId, location_id: this.selectedLocationId, user_id: this.currentUserId },
          { headers: this.apiHeaders() },
        );
        if (start.data?.ok) {
          this.raidCombatId = start.data.combat_id;
          this.notify(`⚔️ Рейд начат, combat #${this.raidCombatId}`);
        }
      } catch (e) {
        this.notify(`❌ ${e?.response?.data?.detail || 'Не удалось начать рейд'}`);
      }
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
          user_id: this.currentUserId,
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
          viewMode:     this.viewMode,
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
        if (data.viewMode) this.viewMode = data.viewMode;
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

    /**
     * Инициализирует или переключает сцену деревни (вид сверху / 3-е лицо).
     * @param {string} containerId
     */
    initVillageScene(containerId) {
      if (this.viewMode === 'third') {
        this.initThirdPersonScene(containerId);
      } else {
        this.initializeMap(containerId);
      }
    },

    /** Показывает кнопку смены вида. В тест-режиме — всем. */
    canToggleViewMode() {
      return this.viewModeTest || this.hasSubscription;
    },

    /** Переключает режим вида (вид сверху ↔ 3-е лицо). */
    toggleViewMode() {
      this.viewMode = this.viewMode === 'top' ? 'third' : 'top';
    },

    initializeMap(containerId) {
      const container = document.getElementById(containerId);
      if (!container) return;
      this.mapLoading = true;

      /* Уничтожаем 3D-режим если был */
      if (this.pixiApp && this.pixiApp._thirdPerson) {
        this.pixiApp.destroy(true);
        this.pixiApp = null;
        this.pixiWorldContainer = null;
        this.pixiCharSprite = null;
      }

      if (!this.pixiApp) {
        this.pixiApp = new PIXI.Application({
          width:           container.offsetWidth  || 640,
          height:          container.offsetHeight || 480,
          backgroundColor: 0x1a1610,
          antialias:       true,
          resizeTo:        container,
        });
        this.pixiApp._thirdPerson = false;
        container.appendChild(this.pixiApp.view);
      }

      axios.get(`${API_URL}/map`).then(r => {
        this.mapData = r.data;
        this.renderMap();
      }).catch(() => {
        this.renderFallbackMap();
      }).finally(() => { this.mapLoading = false; });
    },

    renderMap() {
      if (!this.pixiApp || !this.mapData) return;
      /* Чистим старые слои перед перерисовкой */
      this.pixiApp.stage.removeChildren();

      const cont  = new PIXI.Container();
      const tileW = 64, tileH = 32;

      (this.mapData.tiles || []).forEach(tile => {
        const color = this.getColorForTileType(tile.type);
        const g = new PIXI.Graphics();
        g.beginFill(color, 0.85);
        g.lineStyle(1, 0x000000, 0.2);
        g.drawPolygon([
          tileW/2, 0,
          tileW,   tileH/2,
          tileW/2, tileH,
          0,       tileH/2,
        ]);
        g.endFill();
        g.x = (tile.x - tile.y) * tileW/2;
        g.y = (tile.x + tile.y) * tileH/2;
        /* Tooltip при наведении */
        if (tile.name) {
          g.eventMode = 'static';
          g.cursor = 'help';
          g.on('pointerover', () => this.notify(`📍 ${tile.name}`));
        }
        cont.addChild(g);
      });

      cont.x = this.pixiApp.screen.width  / 2;
      cont.y = 40;
      this.pixiApp.stage.addChild(cont);
    },

    /** Рисует заглушку карты когда API недоступен. */
    renderFallbackMap() {
      if (!this.pixiApp) return;
      this.pixiApp.stage.removeChildren();
      const g = new PIXI.Graphics();
      g.beginFill(0x2e2618);
      g.drawRect(0, 0, this.pixiApp.screen.width, this.pixiApp.screen.height);
      g.endFill();
      const text = new PIXI.Text('Карта недоступна — проверь подключение к API', { fontSize:14, fill:0x9a8a6a, align:'center' });
      text.x = this.pixiApp.screen.width  / 2 - text.width  / 2;
      text.y = this.pixiApp.screen.height / 2 - text.height / 2;
      this.pixiApp.stage.addChild(g, text);
    },

    /* ══════════════════════════════════════
       РЕЖИМ ОТ 3-ГО ЛИЦА
       ══════════════════════════════════════ */

    /**
     * Инициализирует PIXI-сцену в режиме 3-го лица.
     * Камера следует за персонажем; клик по тайлу / WASD — движение.
     * @param {string} containerId
     */
    initThirdPersonScene(containerId) {
      const container = document.getElementById(containerId);
      if (!container) return;

      /* Пересоздаём приложение если переключились с top-down */
      if (this.pixiApp && !this.pixiApp._thirdPerson) {
        this.pixiApp.destroy(true);
        this.pixiApp = null;
      }

      if (!this.pixiApp) {
        this.pixiApp = new PIXI.Application({
          width:           container.offsetWidth  || 640,
          height:          container.offsetHeight || 480,
          backgroundColor: 0x0d1117,
          antialias:       true,
          resizeTo:        container,
        });
        this.pixiApp._thirdPerson = true;
        container.appendChild(this.pixiApp.view);
      }

      /* Загружаем карту и рисуем 3D-сцену */
      const draw = (tiles) => {
        this.pixiApp.stage.removeChildren();
        this.pixiWorldContainer = new PIXI.Container();
        this.pixiApp.stage.addChild(this.pixiWorldContainer);
        this._thirdPersonTiles = tiles;
        this.renderThirdPersonScene();
      };

      if (this.mapData) {
        draw(this.mapData.tiles || []);
      } else {
        this.mapLoading = true;
        axios.get(`${API_URL}/map`).then(r => {
          this.mapData = r.data;
          draw(r.data.tiles || []);
        }).catch(() => draw([])).finally(() => { this.mapLoading = false; });
      }
    },

    /**
     * Рисует мир и персонажа в режиме 3-го лица.
     * Контейнер мира сдвигается так, чтобы персонаж был в центре экрана.
     */
    renderThirdPersonScene() {
      if (!this.pixiApp || !this.pixiWorldContainer) return;
      this.pixiWorldContainer.removeChildren();

      const tileW = 80, tileH = 40;
      const tiles = this._thirdPersonTiles || [];
      const { tileX: cx, tileY: cy } = this.playerChar;

      /* Рисуем тайлы вокруг персонажа (в радиусе 12 тайлов) */
      tiles.forEach(tile => {
        const color = this.getColorForTileType(tile.type);
        const g = new PIXI.Graphics();
        const dist = Math.abs(tile.x - cx) + Math.abs(tile.y - cy);
        g.beginFill(color, dist < 6 ? 0.95 : 0.6);
        g.lineStyle(1, 0x000000, 0.15);
        g.drawPolygon([ tileW/2,0, tileW,tileH/2, tileW/2,tileH, 0,tileH/2 ]);
        g.endFill();
        g.x = (tile.x - tile.y) * tileW/2;
        g.y = (tile.x + tile.y) * tileH/2;
        /* Клик по тайлу = переместить персонажа */
        g.eventMode = 'static';
        g.cursor = 'pointer';
        g.on('pointerdown', () => this.moveCharToTile(tile.x, tile.y));
        if (tile.name) {
          const lbl = new PIXI.Text(tile.name, { fontSize:9, fill:0xdddddd });
          lbl.x = g.x + tileW/2 - lbl.width/2;
          lbl.y = g.y + tileH/2 - lbl.height/2;
          this.pixiWorldContainer.addChild(lbl);
        }
        this.pixiWorldContainer.addChild(g);
      });

      /* Спрайт персонажа */
      const charX = (cx - cy) * tileW/2;
      const charY = (cx + cy) * tileH/2;
      const charG = new PIXI.Graphics();
      charG.beginFill(0xf59e0b);
      charG.lineStyle(2, 0xffd700, 1);
      charG.drawPolygon([ tileW/2,0, tileW,tileH/2, tileW/2,tileH, 0,tileH/2 ]);
      charG.endFill();
      charG.x = charX;
      charG.y = charY;
      this.pixiCharSprite = charG;

      /* Индикатор HP над персонажем */
      const hpBar = new PIXI.Graphics();
      const hpW = 40, hpH = 5;
      hpBar.beginFill(0x333333);
      hpBar.drawRect(0, 0, hpW, hpH);
      hpBar.endFill();
      hpBar.beginFill(0x22c55e);
      hpBar.drawRect(0, 0, Math.round(hpW * this.playerHP / this.playerMaxHP), hpH);
      hpBar.endFill();
      hpBar.x = charX + tileW/2 - hpW/2;
      hpBar.y = charY - 10;

      /* Метка направления над персонажем */
      const dirLabel = new PIXI.Text(this.playerChar.dir || 'S', { fontSize: 10, fill: 0xffd700, fontWeight: 'bold' });
      dirLabel.x = charX + tileW / 2 - dirLabel.width / 2;
      dirLabel.y = charY - 22;

      this.pixiWorldContainer.addChild(charG, hpBar, dirLabel);

      /* Смещаем контейнер мира так, чтобы персонаж был в центре */
      const sc = this.pixiApp.screen;
      this.pixiWorldContainer.x = sc.width  / 2 - charX - tileW/2;
      this.pixiWorldContainer.y = sc.height / 2 - charY - tileH/2;
    },

    /**
     * Перемещает персонажа на тайл (tx, ty) и перерисовывает сцену.
     * @param {number} tx
     * @param {number} ty
     */
    moveCharToTile(tx, ty) {
      this.playerChar.tileX = tx;
      this.playerChar.tileY = ty;
      this.playerChar.moving = true;
      this.renderThirdPersonScene();
      setTimeout(() => { this.playerChar.moving = false; }, 300);
    },

    /**
     * Обрабатывает клавиши WASD / горячие клавиши скиллов в 3-м лице.
     * @param {KeyboardEvent} e
     */
    handleGameKey(e) {
      if (this.viewMode !== 'third' || this.activeTab !== 'village') return;
      if (['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) e.preventDefault();
      const { tileX, tileY } = this.playerChar;
      /* Направление + новые координаты */
      const moves = {
        'w':          [tileX - 1, tileY,     'N'],
        'ArrowUp':    [tileX - 1, tileY,     'N'],
        's':          [tileX + 1, tileY,     'S'],
        'ArrowDown':  [tileX + 1, tileY,     'S'],
        'a':          [tileX,     tileY - 1, 'W'],
        'ArrowLeft':  [tileX,     tileY - 1, 'W'],
        'd':          [tileX,     tileY + 1, 'E'],
        'ArrowRight': [tileX,     tileY + 1, 'E'],
      };
      if (moves[e.key]) {
        const [nx, ny, dir] = moves[e.key];
        this.playerChar.dir = dir;
        if (nx >= 0 && ny >= 0 && nx < 32 && ny < 32) this.moveCharToTile(nx, ny);
        return;
      }
      /* Горячие клавиши скиллов */
      const skill = this.skills.find(s => s.key === e.key.toUpperCase());
      if (skill) this.activateSkill(skill.id);
    },

    /**
     * Активирует скилл с проверкой кулдауна.
     * @param {string} skillId
     */
    async activateSkill(skillId) {
      const skill = this.skills.find(s => s.id === skillId);
      if (!skill || skill.cd > 0) return;

      /* Стоимость маны */
      const manaCost = { attack: 10, heal: 15, dash: 8 };
      const cost = manaCost[skillId] ?? 10;
      if (this.playerMana < cost) {
        this.notify(`❌ Нет маны (нужно ${cost}, есть ${this.playerMana})`);
        return;
      }
      this.playerMana = Math.max(0, this.playerMana - cost);
      skill.cd = skill.maxCd;

      if (this.raidCombatId) {
        try {
          const r = await axios.post(
            `${API_URL}/survival/combat/action`,
            { combat_id: this.raidCombatId, skill_id: skillId, user_id: this.currentUserId },
            { headers: this.apiHeaders() },
          );
          if (r.data?.ok) {
            this.playerHP = Number(r.data.attacker_hp ?? this.playerHP);
            this.addCombatLog(`${skill.icon} ${r.data.log_entry || skill.name} (HP: ${r.data.attacker_hp}/${r.data.defender_hp})`);
            if (r.data.status === 'finished') {
              this.notify('🏁 Рейд завершён');
              this.raidCombatId = null;
            }
          }
        } catch (e) {
          this.notify(`❌ ${e?.response?.data?.detail || 'Ошибка боевого API'}`);
        }
      } else if (skillId === 'attack') {
        const dmg = 10 + Math.floor(Math.random() * 10);
        this.addCombatLog(`${skill.icon} Атака: −${dmg} HP врагу`);
      } else if (skillId === 'heal') {
        const heal = Math.min(30, this.playerMaxHP - this.playerHP);
        this.playerHP += heal;
        this.addCombatLog(`${skill.icon} Лечение: +${heal} HP`);
        if (this.viewMode === 'third') this.renderThirdPersonScene();
      } else if (skillId === 'dash') {
        this.addCombatLog(`${skill.icon} Рывок!`);
      }
      this.notify(`${skill.icon} ${skill.name}`);

      /* Кулдаун — уменьшаем каждую секунду */
      const tick = setInterval(() => {
        skill.cd = Math.max(0, skill.cd - 1);
        if (skill.cd === 0) clearInterval(tick);
      }, 1000);
    },

    /** Добавляет запись в лог боя (максимум 10 строк). */
    addCombatLog(text) {
      this.combatLog.unshift({ id: Date.now(), text });
      if (this.combatLog.length > 10) this.combatLog.pop();
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
      }).catch(() => this.renderEditorMap());
    },

    /**
     * Рисует сетку редактора с уже размещёнными тайлами.
     * Очищает stage перед каждой перерисовкой — без дублирования слоёв.
     */
    renderEditorMap() {
      if (!this.editorApp) return;
      this.editorApp.stage.removeChildren();

      if (!this.editorMapData) this.editorMapData = { tiles: [], width: 16, height: 16 };
      const tileW = 64, tileH = 32;
      const cols = this.editorMapData.width  || 16;
      const rows = this.editorMapData.height || 16;
      const cont = new PIXI.Container();

      for (let x = 0; x < cols; x++) {
        for (let y = 0; y < rows; y++) {
          const placed = this.editorMapData.tiles.find(t => t.x === x && t.y === y);
          const g = new PIXI.Graphics();
          g.lineStyle(1, 0x3d3320, placed ? 0.8 : 0.4);
          if (placed) {
            g.beginFill(this.getColorForTileType(placed.type), 0.92);
          } else {
            g.beginFill(0x2e2618, 0.7);
          }
          g.drawPolygon([ tileW/2,0, tileW,tileH/2, tileW/2,tileH, 0,tileH/2 ]);
          g.endFill();
          g.x = (x - y) * tileW/2;
          g.y = (x + y) * tileH/2;
          g.eventMode = 'static';
          g.cursor = 'pointer';
          g.on('pointerdown', () => this.placeTile(x, y));
          g.on('pointermove', () => { this.cursorCoords = { x, y }; });
          cont.addChild(g);

          /* Подпись имени размещённого тайла */
          if (placed?.name) {
            const lbl = new PIXI.Text(placed.name, { fontSize:8, fill:0xffd700 });
            lbl.x = g.x + tileW/2 - lbl.width/2;
            lbl.y = g.y + tileH/2 - lbl.height/2;
            cont.addChild(lbl);
          }
        }
      }

      cont.x = this.editorApp.screen.width / 2;
      cont.y = 40;
      this.editorApp.stage.addChild(cont);
    },

    /** Синоним для обратной совместимости (раньше вызывался отдельно). */
    renderEditorGrid() {
      this.renderEditorMap();
    },

    placeTile(x, y) {
      if (!this.editorMapData) this.editorMapData = { tiles: [], width: 16, height: 16 };
      const idx = this.editorMapData.tiles.findIndex(t => t.x === x && t.y === y);
      if (this.editorTool === 'erase') {
        /* Режим ластика — только удалять */
        if (idx !== -1) this.editorMapData.tiles.splice(idx, 1);
        this.selectedTileProps = null;
      } else {
        if (!this.selectedAsset.type) { this.notify('Выберите ассет из панели слева'); return; }
        if (idx !== -1) this.editorMapData.tiles.splice(idx, 1);
        this.editorMapData.tiles.push({ x, y, type: this.selectedAsset.id, name: this.selectedAsset.name });
        this.selectedTileProps = { x, y, type: this.selectedAsset.id, name: this.selectedAsset.name };
      }
      this.renderEditorMap();
    },

    async saveMap() {
      if (!this.editorMapData) { this.notify('Нечего сохранять'); return; }
      if (!this.editorApiKey) { this.notify('❌ Укажи Editor API Key в панели справа'); return; }
      const count = this.editorMapData.tiles?.length ?? 0;
      if (!confirm(`Сохранить карту из ${count} тайлов на сервер?`)) return;
      this.editorSaving = true;
      try {
        await axios.put(`${API_URL}/map`, this.editorMapData, {
          headers: { 'X-API-Key': this.editorApiKey }
        });
        this.notify('✅ Карта сохранена');
      } catch (e) {
        if (e.response?.status === 401) this.notify('❌ Неверный Editor API Key');
        else if (e.response?.status === 503) this.notify('❌ Сохранение отключено — задай EDITOR_API_KEY на сервере');
        else this.notify('❌ Ошибка сохранения — проверь подключение к API');
      } finally {
        this.editorSaving = false;
      }
    },

    /** Сохраняет Editor API Key в localStorage. */
    saveEditorApiKey() {
      localStorage.setItem('editor_api_key', this.editorApiKey);
      this.notify('✅ Editor API Key сохранён');
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

    /* ══════════════════════════════════════
       АДМИН-ПАНЕЛЬ ТИГРИТ
       ══════════════════════════════════════ */

    /** Сохраняет Admin API Key в localStorage. */
    saveAdminApiKey() {
      localStorage.setItem('tigrit_admin_key', this.adminApiKey);
      this.adminMsg = '✅ Admin API Key сохранён';
      this.adminMsgOk = true;
      setTimeout(() => { this.adminMsg = ''; }, 3000);
    },

    /** Открытие вкладки Админ — автозагрузка данных и статус API. Debounce двойного вызова. */
    async adminOpenTab() {
      if (this._adminLoadingInProgress) return;
      this._adminLoadingInProgress = true;
      await Promise.all([this.adminLoadVillage(), this.adminCheckStatus()]);
      this._adminLoadingInProgress = false;
    },

    /** Проверяет статус Admin API (db_connected, admin_key_configured). */
    async adminCheckStatus() {
      try {
        const r = await axios.get(`${API_URL}/admin/status`, {
          headers: this.adminApiKey ? { 'X-Admin-Key': this.adminApiKey } : {},
        });
        this.adminStatus = r.data;
      } catch (e) {
        this.adminStatus = { ok: false, db_connected: false, admin_key_configured: false };
      }
    },

    /** Загружает текущие данные деревни из Admin API (полный SELECT с name). */
    async adminLoadVillage() {
      this.adminLoading = true;
      try {
        const headers = this.adminApiKey ? { 'X-Admin-Key': this.adminApiKey } : {};
        const r = await axios.get(`${API_URL}/admin/village/1`, { headers });
        const v = r.data || {};
        this.adminVillage = {
          name:           v.name          || 'Тигрит',
          level:          v.level         || 1,
          xp:             v.xp            || 0,
          activity:       v.activity      || 0,
          population:     v.population    || 0,
          population_max: v.population_max || 50,
          build_name:     v.build_name    || '',
          build_progress: v.build_progress || 0,
          resources:      { wood:0, stone:0, gold:0, food:0, influence:0, ...(v.resources || {}) },
        };
        this._adminVillageLoaded = true;
        this.adminMsg = '✅ Данные деревни загружены';
        this.adminMsgOk = true;
      } catch (e) {
        const status = e.response?.status;
        const detail = e.response?.data?.error || e.response?.data?.detail || e.message;
        if (status === 401 || status === 503) {
          this.adminMsg = '⚠️ Данные без ключа — введите Admin API Key для загрузки';
          this.adminMsgOk = false;
          /* Fallback на публичный /api/village */
          try {
            const fb = await axios.get(`${API_URL}/village`);
            if (fb.data) {
              const v = fb.data;
              this.adminVillage = {
                name: v.name || 'Тигрит', level: v.level || 1, xp: v.xp || 0,
                activity: v.activity || 0, population: v.population || 0,
                population_max: v.population_max || 50,
                build_name: v.build_name || '', build_progress: v.build_progress || 0,
                resources: { wood:0, stone:0, gold:0, food:0, influence:0, ...(v.resources || {}) },
              };
            }
          } catch {}
        } else if (status === 404) {
          this.adminMsg = '❌ Деревня не найдена — INSERT INTO tigrit_village(id) VALUES(1)';
          this.adminMsgOk = false;
        } else {
          this.adminMsg = `❌ Нет связи с API: ${detail}`;
          this.adminMsgOk = false;
        }
      } finally {
        this.adminLoading = false;
        setTimeout(() => { this.adminMsg = ''; }, 5000);
      }
    },

    /**
     * Сохраняет изменения деревни через Admin API.
     * Использует PATCH /api/admin/village/1 с заголовком X-Admin-Key.
     */
    async adminSaveVillage() {
      if (!this.adminApiKey) {
        this.adminMsg = '❌ Укажи Admin API Key в поле выше'; this.adminMsgOk = false; return;
      }
      this.adminLoading = true;
      try {
        const r = await axios.patch(`${API_URL}/admin/village/1`, this.adminVillage, {
          headers: { 'X-Admin-Key': this.adminApiKey }
        });
        /* Обновляем вид деревни свежими данными с сервера */
        await this.fetchVillageData();
        if (r.data?.village) {
          const v = r.data.village;
          this.adminVillage = { ...this.adminVillage, ...v };
        }
        this.adminMsg = '✅ Деревня обновлена'; this.adminMsgOk = true;
      } catch (e) {
        const status = e.response?.status;
        const err = e.response?.data?.error || e.response?.data?.detail || e.message;
        if (status === 401)      this.adminMsg = '❌ Неверный Admin API Key';
        else if (status === 503) this.adminMsg = '❌ БД недоступна — tigrit-api не подключён к PostgreSQL';
        else if (status === 422) this.adminMsg = `❌ Миграция нужна: ${err}. Запустите run_migrations.py`;
        else if (status === 404) this.adminMsg = '❌ Деревня не найдена в БД — создайте запись id=1';
        else if (!status)        this.adminMsg = '❌ Нет связи с API — проверь что tigrit-api запущен';
        else                     this.adminMsg = `❌ Ошибка ${status}: ${err}`;
        this.adminMsgOk = false;
      } finally {
        this.adminLoading = false;
        setTimeout(() => { this.adminMsg = ''; }, 6000);
      }
    },

    /**
     * Сохраняет XP/level игрока через Admin API.
     * PATCH /api/admin/user/{userId}
     */
    async adminSaveUser() {
      if (!this.adminApiKey) { this.adminMsg = '❌ Укажи Admin API Key'; this.adminMsgOk = false; return; }
      if (!this.adminUser.userId) { this.adminMsg = '❌ Укажи User ID'; this.adminMsgOk = false; return; }
      this.adminLoading = true;
      try {
        const body = {};
        if (this.adminUser.xp    !== undefined) body.xp    = this.adminUser.xp;
        if (this.adminUser.level !== undefined) body.level = this.adminUser.level;
        if (this.adminUser.race)                body.race  = this.adminUser.race;
        if (this.adminUser.clazz)               body.clazz = this.adminUser.clazz;
        const r = await axios.patch(`${API_URL}/admin/user/${this.adminUser.userId}`, body, {
          headers: { 'X-Admin-Key': this.adminApiKey }
        });
        /* Обновляем форму актуальными данными с сервера */
        if (r.data?.user) this.adminUserInfo = r.data.user;
        this.adminMsg = `✅ Игрок ${this.adminUser.userId} обновлён`;
        this.adminMsgOk = true;
      } catch (e) {
        const status = e.response?.status;
        const err = e.response?.data?.error || e.response?.data?.detail || e.message;
        if (status === 401)      this.adminMsg = '❌ Неверный Admin API Key';
        else if (status === 503) this.adminMsg = '❌ БД недоступна';
        else if (status === 422) this.adminMsg = `❌ Ошибка валидации: ${err}`;
        else if (status === 404) this.adminMsg = `❌ Игрок ${this.adminUser.userId} не найден в tigrit_user_profile`;
        else if (!status)        this.adminMsg = '❌ Нет связи с API';
        else                     this.adminMsg = `❌ Ошибка ${status}: ${err}`;
        this.adminMsgOk = false;
      } finally {
        this.adminLoading = false;
        setTimeout(() => { this.adminMsg = ''; }, 5000);
      }
    },

    /**
     * Быстрые активации: завершить стройку, залить ресурсы и т.д.
     * @param {string} action
     */
    async adminQuickAction(action) {
      if (!this.adminApiKey) {
        this.adminMsg = '❌ Укажи Admin API Key'; this.adminMsgOk = false; return;
      }
      /* Guard: если данные деревни ещё не загружены — сначала загрузить */
      if (!this._adminVillageLoaded) {
        await this.adminLoadVillage();
      }
      this.adminLoading = true;
      try {
        const r = await axios.post(`${API_URL}/admin/village/1/activate`, { action }, {
          headers: { 'X-Admin-Key': this.adminApiKey }
        });
        if (r.data?.village) {
          const v = r.data.village;
          this.adminVillage = { ...this.adminVillage, ...v };
        }
        await this.fetchVillageData();
        this.notify(`⚡ Выполнено: ${action}`);
        this.adminMsg = `✅ Активация: ${action}`; this.adminMsgOk = true;
      } catch (e) {
        const status = e.response?.status;
        const err = e.response?.data?.error || e.response?.data?.detail || e.message;
        if (status === 400) this.adminMsg = `❌ Неизвестное действие: ${action}`;
        else if (status === 401) this.adminMsg = '❌ Неверный Admin API Key';
        else this.adminMsg = `❌ Ошибка: ${err}`;
        this.adminMsgOk = false;
      } finally {
        this.adminLoading = false;
        setTimeout(() => { this.adminMsg = ''; }, 5000);
      }
    },

    /** Поиск игрока по username с debounce 300мс. */
    adminSearchUsers() {
      clearTimeout(this._userSearchTimer);
      if (!this.adminUserSearch.trim()) { this.adminUserResults = []; return; }
      this._userSearchTimer = setTimeout(async () => {
        try {
          const r = await axios.get(`${API_URL}/admin/users`, {
            params: { search: this.adminUserSearch, limit: 10 },
            headers: this.adminApiKey ? { 'X-Admin-Key': this.adminApiKey } : {},
          });
          this.adminUserResults = r.data?.players || [];
        } catch { this.adminUserResults = []; }
      }, 300);
    },

    /** Выбрать игрока из результатов поиска и заполнить форму. */
    adminSelectUser(player) {
      this.adminUser.userId = player.user_id;
      this.adminUser.xp     = player.xp    || 0;
      this.adminUser.level  = player.level  || 1;
      this.adminUser.race   = player.race   || '';
      this.adminUser.clazz  = player.clazz  || '';
      this.adminUserInfo    = player;
      this.adminUserResults = [];
      this.adminUserSearch  = player.username || '';
    },
  },
});

app.mount('#app');
