import { createApp } from 'vue';
import * as PIXI from 'pixi.js';
import axios from 'axios';

// Относительный /api при раздаче через тот же хост (nginx proxy)
const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) || '/api';
/** Белый список: только этот бот для ссылок «В бот». Не подставлять chat_id из БД (open redirect). */
const BOT_USERNAME = 'PHXPW';

const app = createApp({
    data() {
        return {
            activeTab: 'village',
            village: {
                level: 0,
                activity: 0,
                resources: 0,
                population: 0,
                build_name: '',
                build_progress: 0
            },
            players: [],
            events: [],
            activeEvents: [],
            assets: {
                tiles: [],
                buildings: [],
                characters: []
            },
            selectedAsset: { type: null, id: null, name: null },
            pixiApp: null,
            mapData: null,
            /** Статический список команд бота для блока «Команды бота». */
            botCommands: [
                { cmd: '/start', desc: 'Начать, меню' },
                { cmd: '/top', desc: 'Топ игроков' },
                { cmd: '/village', desc: 'Карта деревни' },
                { cmd: '/me', desc: 'Мой профиль' },
                { cmd: '/balance', desc: 'Баланс' },
                { cmd: '/friends', desc: 'Друзья' },
                { cmd: '/spawn_event', desc: 'Запуск ивента (админ)' }
            ]
        };
    },

    mounted() {
        this.fetchVillageData();
        this.fetchPlayers();
        this.fetchEvents();
        this.fetchActiveEvents();
        this.fetchAssets();
        
        setInterval(() => {
            this.fetchVillageData();
            this.fetchEvents();
            this.fetchActiveEvents();
        }, 5000);
        
        // Инициализация карты при активации вкладки деревни
        this.$watch('activeTab', (newTab) => {
            if (newTab === 'village' && !this.pixiApp) {
                this.$nextTick(() => this.initializeMap('map-container'));
            } else if (newTab === 'editor') {
                this.$nextTick(() => this.initializeEditor('editor-canvas'));
            }
        });
    },
    
    methods: {
        async fetchVillageData() {
            try {
                const response = await axios.get(`${API_URL}/village`);
                this.village = response.data;
            } catch (error) {
                console.error('Ошибка при загрузке данных деревни:', error);
            }
        },
        
        async fetchPlayers() {
            try {
                const response = await axios.get(`${API_URL}/users`, { params: { limit: 20 } });
                this.players = response.data;
            } catch (error) {
                console.error('Ошибка при загрузке игроков:', error);
            }
        },
        
        async fetchEvents() {
            try {
                const response = await axios.get(`${API_URL}/events`);
                this.events = response.data;
            } catch (error) {
                console.error('Ошибка при загрузке событий:', error);
            }
        },
        
        async fetchAssets() {
            try {
                const response = await axios.get(`${API_URL}/assets`);
                this.assets = response.data;
            } catch (error) {
                console.error('Ошибка при загрузке ассетов:', error);
            }
        },

        async fetchActiveEvents() {
            try {
                const response = await axios.get(`${API_URL}/events/active`);
                this.activeEvents = response.data || [];
            } catch (error) {
                console.error('Ошибка при загрузке активных ивентов:', error);
            }
        },

        getPlayerColor(player) {
            // Простая функция для генерации цвета на основе имени
            let hash = 0;
            const name = player.username || 'anon';
            for (let i = 0; i < name.length; i++) {
                hash = name.charCodeAt(i) + ((hash << 5) - hash);
            }
            const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
            return `#${'00000'.substring(0, 6 - c.length)}${c}`;
        },
        
        /** Форматирование времени: unix (сек) или ISO-строка. */
        formatTime(timestamp) {
            if (timestamp == null) return '—';
            const date = typeof timestamp === 'number' ? new Date(timestamp * 1000) : new Date(timestamp);
            return isNaN(date.getTime()) ? String(timestamp) : date.toLocaleString();
        },
        
        getEventType(kind) {
            const types = {
                'msg': 'Сообщение',
                'event': 'Событие',
                'dialogue': 'Диалог',
                'external': 'Внешнее'
            };
            return types[kind] || kind;
        },
        /** Цвет для тайла карты по type: из buildings или tiles (hex → number для PIXI). */
        getColorForTileType(type) {
            if (type === 'center') return 0xd3b17d;
            const building = (this.assets.buildings || []).find(b => (b.id || b) === type);
            if (building && building.color) return parseInt(String(building.color).replace('#', ''), 16);
            const tile = (this.assets.tiles || []).find(t => (t.id || t) === type);
            if (tile && tile.color) return parseInt(String(tile.color).replace('#', ''), 16);
            return 0x444444;
        },
        initializeMap(containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            
            // Создаем приложение PIXI
            this.pixiApp = new PIXI.Application({
                width: 640,
                height: 480,
                backgroundColor: 0x5da85d,
                antialias: false
            });
            container.appendChild(this.pixiApp.view);
            
            // Загрузка данных карты
            axios.get(`${API_URL}/map`).then(response => {
                this.mapData = response.data;
                this.renderMap();
            });
        },
        
        renderMap() {
            if (!this.pixiApp || !this.mapData) return;
            
            const container = new PIXI.Container();
            this.pixiApp.stage.addChild(container);
            
            // Создаем пиксельные тайлы для отображения
            // Это упрощенная версия, где мы просто рисуем разноцветные прямоугольники
            const tileSize = 32;
            
            // Создаем базовую сетку
            for (let x = 0; x < this.mapData.width; x++) {
                for (let y = 0; y < this.mapData.height; y++) {
                    const tile = new PIXI.Graphics();
                    tile.beginFill(0x5da85d);
                    tile.drawRect(0, 0, tileSize, tileSize);
                    tile.endFill();
                    tile.x = x * tileSize;
                    tile.y = y * tileSize;
                    container.addChild(tile);
                }
            }
            
            // Размещаем объекты из данных карты (цвет из assets)
            this.mapData.tiles.forEach(tile => {
                const color = this.getColorForTileType(tile.type);
                const obj = new PIXI.Graphics();
                obj.beginFill(color);
                obj.drawRect(0, 0, tileSize, tileSize);
                obj.endFill();
                obj.x = tile.x * tileSize;
                obj.y = tile.y * tileSize;
                
                // Добавляем текст если нужно
                if (tile.name) {
                    const text = new PIXI.Text(tile.name, {
                        fontSize: 10,
                        fill: 0xffffff
                    });
                    text.x = 2;
                    text.y = 2;
                    obj.addChild(text);
                }
                
                container.addChild(obj);
            });
            
            // Центрируем карту
            container.x = (this.pixiApp.screen.width - this.mapData.width * tileSize) / 2;
            container.y = (this.pixiApp.screen.height - this.mapData.height * tileSize) / 2;
        },
        
        initializeEditor(containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            
            // Создаем отдельное приложение PIXI для редактора
            if (this.editorApp) {
                container.innerHTML = '';
                container.appendChild(this.editorApp.view);
                return;
            }
            
            this.editorApp = new PIXI.Application({
                width: 640,
                height: 480,
                backgroundColor: 0x333333,
                antialias: false
            });
            container.appendChild(this.editorApp.view);
            
            // Загружаем карту для редактирования
            axios.get(`${API_URL}/map`).then(response => {
                this.editorMapData = JSON.parse(JSON.stringify(response.data));
                this.renderEditorMap();
            });
        },
        
        renderEditorMap() {
            // Аналогично renderMap, но с возможностью редактирования
            if (!this.editorApp || !this.editorMapData) return;
            
            const container = new PIXI.Container();
            this.editorApp.stage.addChild(container);
            
            const tileSize = 32;
            
            // Создаем базовую сетку
            for (let x = 0; x < this.editorMapData.width; x++) {
                for (let y = 0; y < this.editorMapData.height; y++) {
                    const tile = new PIXI.Graphics();
                    tile.beginFill(0x5da85d);
                    tile.lineStyle(1, 0x333333);
                    tile.drawRect(0, 0, tileSize, tileSize);
                    tile.endFill();
                    tile.x = x * tileSize;
                    tile.y = y * tileSize;
                    
                    // Делаем тайл интерактивным
                    tile.eventMode = 'static';
                    tile.cursor = 'pointer';
                    tile.on('pointerdown', () => this.placeTile(x, y));
                    
                    container.addChild(tile);
                }
            }
            
            // Отрисовка существующих объектов
            this.renderEditorTiles(container, tileSize);
            
            // Центрируем карту
            container.x = (this.editorApp.screen.width - this.editorMapData.width * tileSize) / 2;
            container.y = (this.editorApp.screen.height - this.editorMapData.height * tileSize) / 2;
        },
        
        renderEditorTiles(container, tileSize) {
            // Очищаем текущие тайлы (кроме базовой сетки)
            const children = [...container.children];
            for (let i = this.editorMapData.width * this.editorMapData.height; i < children.length; i++) {
                container.removeChild(children[i]);
            }
            
            // Отрисовываем текущие тайлы (цвет из ассетов)
            this.editorMapData.tiles.forEach(tile => {
                const color = this.getColorForTileType(tile.type);
                const obj = new PIXI.Graphics();
                obj.beginFill(color);
                obj.drawRect(0, 0, tileSize, tileSize);
                obj.endFill();
                obj.x = tile.x * tileSize;
                obj.y = tile.y * tileSize;
                
                // Добавляем текст если нужно
                if (tile.name) {
                    const text = new PIXI.Text(tile.name, {
                        fontSize: 10,
                        fill: 0xffffff
                    });
                    text.x = 2;
                    text.y = 2;
                    obj.addChild(text);
                }
                
                container.addChild(obj);
            });
        },
        
        placeTile(x, y) {
            if (!this.selectedAsset.type || this.selectedAsset.id == null) {
                alert('Сначала выберите тип тайла или объекта из панели слева');
                return;
            }
            const existingTileIndex = this.editorMapData.tiles.findIndex(t => t.x === x && t.y === y);
            if (existingTileIndex !== -1) {
                this.editorMapData.tiles.splice(existingTileIndex, 1);
            }
            const newTile = {
                x,
                y,
                type: this.selectedAsset.id,
                name: this.selectedAsset.name || this.selectedAsset.id
            };
            
            this.editorMapData.tiles.push(newTile);
            
            // Перерисовываем карту
            const container = this.editorApp.stage.children[0];
            const tileSize = 32;
            this.renderEditorTiles(container, tileSize);
        },
        
        /** URL «В бот» только по whitelist (BOT_USERNAME). eventId — id ивента, не chat_id из БД. */
        botEventLink(eventId) {
            return `https://t.me/${BOT_USERNAME}?start=event_${eventId}`;
        },
        /** Выбор ассета в редакторе: type 'tile'|'building', объект с id/name. */
        selectAsset(assetType, item) {
            const id = typeof item === 'object' ? (item.id || item) : item;
            const name = typeof item === 'object' ? (item.name || id) : id;
            this.selectedAsset = { type: assetType, id, name };
        },
        
        /** Сохранение карты на бэкенд. Ключ редактора: VITE_EDITOR_API_KEY (при сборке). */
        async saveMap() {
            const apiKey = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_EDITOR_API_KEY) || '';
            const headers = { 'Content-Type': 'application/json' };
            if (apiKey) headers['X-API-Key'] = apiKey;
            try {
                const res = await axios.put(`${API_URL}/map`, this.editorMapData, { headers });
                if (res.data && res.data.ok) {
                    alert('Карта сохранена.');
                    return;
                }
            } catch (err) {
                const status = err.response?.status;
                const detail = err.response?.data?.detail || err.message;
                if (status === 401) {
                    alert('Неверный или отсутствующий ключ редактора (X-API-Key). Задайте VITE_EDITOR_API_KEY при сборке.');
                    return;
                }
                if (status === 503) {
                    alert('Сохранение карты отключено на сервере (EDITOR_API_KEY не задан).');
                    return;
                }
                if (status === 422) {
                    alert('Некорректные данные карты: ' + (typeof detail === 'string' ? detail : JSON.stringify(detail)));
                    return;
                }
                if (status === 429) {
                    alert('Слишком много запросов. Подождите минуту.');
                    return;
                }
                alert('Ошибка сохранения: ' + (detail || status || 'неизвестная'));
            }
        },
        
        exportMap() {
            // Экспорт карты в JSON файл
            const dataStr = JSON.stringify(this.editorMapData, null, 2);
            const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
            
            const exportFileDefaultName = 'village_map.json';
            
            const linkElement = document.createElement('a');
            linkElement.setAttribute('href', dataUri);
            linkElement.setAttribute('download', exportFileDefaultName);
            linkElement.click();
        },
        
        importMap() {
            document.getElementById('import-map').click();
        },
        
        /** Импорт карты только с диска (локально). При будущей загрузке на сервер — проверять тип/размер, не выполнять как код. */
        handleImport(event) {
            const file = event.target.files[0];
            if (!file) return;
            const MAX_IMPORT_SIZE = 2 * 1024 * 1024; // 2 MB
            if (file.size > MAX_IMPORT_SIZE) {
                alert('Файл слишком большой (макс. 2 МБ)');
                return;
            }
            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const mapData = JSON.parse(e.target.result);
                    if (!mapData || typeof mapData !== 'object') {
                        alert('Некорректный формат JSON');
                        return;
                    }
                    this.editorMapData = mapData;
                    this.renderEditorMap();
                } catch (err) {
                    console.error('Ошибка при чтении файла карты:', err);
                    alert('Ошибка разбора JSON');
                }
            };
            reader.readAsText(file);
            event.target.value = '';
        }
    }
});

app.mount('#app');
