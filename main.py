# main.py - Загальноукраїнський монітор повітряних загроз
import asyncio
import json
import os
import hashlib
from datetime import datetime, timedelta
from telethon import TelegramClient, events
import requests

# ============= КОНФІГУРАЦІЯ =============
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TARGET_CHANNEL = os.getenv('TARGET_CHANNEL_ID')  # Твій канал

# База всіх областей та міст України
REGIONS = {
    'вінницька': ['Вінниця', 'Жмеринка', 'Могилів-Подільський', 'Козятин', 'Хмільник'],
    'волинська': ['Луцьк', 'Ковель', 'Володимир-Волинський', 'Нововолинськ'],
    'дніпропетровська': ['Дніпро', 'Кривий Ріг', 'Кам\'янське', 'Нікополь', 'Павлоград', 'Марганець'],
    'донецька': ['Краматорськ', 'Слов\'янськ', 'Покровськ', 'Бахмут', 'Торецьк'],
    'житомирська': ['Житомир', 'Бердичів', 'Новоград-Волинський', 'Коростень'],
    'закарпатська': ['Ужгород', 'Мукачево', 'Хуст', 'Берегове'],
    'запорізька': ['Запоріжжя', 'Мелітополь', 'Енергодар', 'Бердянськ'],
    'івано-франківська': ['Івано-Франківськ', 'Коломия', 'Калуш', 'Надвірна'],
    'київська': ['Київ', 'Біла Церква', 'Бровари', 'Буча', 'Ірпінь', 'Бориспіль', 'Фастів'],
    'кіровоградська': ['Кропивницький', 'Олександрія', 'Світловодськ'],
    'луганська': ['Сєвєродонецьк', 'Лисичанськ', 'Рубіжне', 'Старобільськ'],
    'львівська': ['Львів', 'Дрогобич', 'Червоноград', 'Стрий', 'Самбір'],
    'миколаївська': ['Миколаїв', 'Первомайськ', 'Южноукраїнськ', 'Вознесенськ'],
    'одеська': ['Одеса', 'Чорноморськ', 'Білгород-Дністровський', 'Ізмаїл'],
    'полтавська': ['Полтава', 'Кременчук', 'Лубни', 'Миргород', 'Комсомольськ'],
    'рівненська': ['Рівне', 'Вараш', 'Дубно', 'Острог'],
    'сумська': ['Суми', 'Конотоп', 'Шостка', 'Охтирка', 'Ромни'],
    'тернопільська': ['Тернопіль', 'Чортків', 'Кременець'],
    'харківська': ['Харків', 'Лозова', 'Ізюм', 'Куп\'янськ', 'Чугуїв'],
    'херсонська': ['Херсон', 'Нова Каховка', 'Каховка'],
    'хмельницька': ['Хмельницький', 'Кам\'янець-Подільський', 'Шепетівка'],
    'черкаська': ['Черкаси', 'Умань', 'Сміла', 'Золотоноша'],
    'чернівецька': ['Чернівці', 'Новодністровськ'],
    'чернігівська': ['Чернігів', 'Ніжин', 'Прилуки', 'Новгород-Сіверський'],
    'крим': ['Сімферополь', 'Севастополь', 'Керч', 'Євпаторія'],
}

# Розгорнутий словник для швидкого пошуку
CITY_TO_REGION = {}
for region, cities in REGIONS.items():
    for city in cities:
        CITY_TO_REGION[city.lower()] = region
        # Додаємо англійські варіанти
        if city == 'Київ':
            CITY_TO_REGION['kyiv'] = region
            CITY_TO_REGION['kiev'] = region
        elif city == 'Дніпро':
            CITY_TO_REGION['dnipro'] = region
            CITY_TO_REGION['dnepro'] = region
        elif city == 'Львів':
            CITY_TO_REGION['lviv'] = region
            CITY_TO_REGION['lwow'] = region

# Офіційні канали (пріоритетні джерела)
OFFICIAL_CHANNELS = [
    'air_alert_ua',           # Карта тривог
    'kpszsu',                 # Командування ПС ЗСУ
    'dsns_telegram',          # ДСНС
    # ОВА областей
    'dnipropetrovskaODA',
    'kharkivoda',
    'lvivoda',
    'oda_kyiv',
    'sumyoda',
    'poltava_ova',
    'ZaporizhzhiaODA',
    'mykolayivoda',
    'odesa_ova',
    'KhersonODA',
    # Додай інші офіційні канали міст
]

# Додаткові канали для моніторингу
ADDITIONAL_CHANNELS = [
    'kharkiv_1654',
    'kyiv_siren',
    'dnipro_pravda',
    'lviv_now',
    'mykolaiv_live',
    # Локальні новини міст
]

ALL_CHANNELS = OFFICIAL_CHANNELS + ADDITIONAL_CHANNELS

# ============= СИСТЕМА АНАЛІЗУ =============

def extract_location(text):
    """Витягує область та місто з тексту"""
    text_lower = text.lower()
    
    found_region = None
    found_city = None
    
    # Шукаємо міста
    for city, region in CITY_TO_REGION.items():
        if city in text_lower:
            found_city = city.title()
            found_region = region
            break
    
    # Шукаємо області
    for region in REGIONS.keys():
        variants = [
            region,
            region.replace('ська', ''),
            region.replace('цька', ''),
            region + ' область',
        ]
        for variant in variants:
            if variant in text_lower:
                found_region = region
                break
    
    return {
        'region': found_region.title() + ' область' if found_region else 'unknown',
        'city': found_city if found_city else 'unknown'
    }

def categorize_threat(text):
    """Визначає тип загрози"""
    text_lower = text.lower()
    
    # БПЛА
    uav_keywords = ['бпла', 'дрон', 'шахед', 'shahed', 'герань', 'ланцет', 'lancet', 'fpv', 'безпілотник']
    if any(kw in text_lower for kw in uav_keywords):
        if any(word in text_lower for word in ['загроза', 'рух', 'напрямок', 'курс', 'летить']):
            return 'UAV_THREAT'
        return 'UAV_SIGHTING'
    
    # Ракети
    missile_keywords = ['ракета', 'іскандер', 'iskander', 'калібр', 'kalibr', 'х-101', 'х-47', 'кинджал', 'kinzhal']
    if any(kw in text_lower for kw in missile_keywords):
        return 'MISSILE_THREAT'
    
    # КАБ/ФАБ
    bomb_keywords = ['каб', 'фаб', 'авіабомба', 'бомба', 'kab', 'fab']
    if any(kw in text_lower for kw in bomb_keywords):
        return 'KAB_FAB_THREAT'
    
    # Тривога
    if 'тривога' in text_lower or 'повітряна' in text_lower:
        return 'AIR_ALERT'
    
    # Відбій
    if 'відбій' in text_lower or 'скасування' in text_lower:
        return 'ALL_CLEAR'
    
    # Вибухи
    if any(word in text_lower for word in ['вибух', 'влучання', 'удар', 'прилетіло']):
        return 'EXPLOSION'
    
    return 'NOT_RELEVANT'

def calculate_urgency(text, category):
    """Розрахунок срочності 0-100"""
    urgency = 0
    text_lower = text.lower()
    
    # Базова срочність за категорією
    category_urgency = {
        'EXPLOSION': 90,
        'MISSILE_THREAT': 80,
        'UAV_THREAT': 70,
        'KAB_FAB_THREAT': 75,
        'AIR_ALERT': 60,
        'UAV_SIGHTING': 40,
        'ALL_CLEAR': 10,
        'NOT_RELEVANT': 0
    }
    urgency = category_urgency.get(category, 0)
    
    # Модифікатори
    if 'терміново' in text_lower or 'urgent' in text_lower:
        urgency += 15
    if 'жертви' in text_lower or 'постраждалі' in text_lower:
        urgency = min(100, urgency + 20)
    if 'підтверджено' in text_lower or 'офіційно' in text_lower:
        urgency += 10
    if 'курс на' in text_lower or 'рух' in text_lower:
        urgency += 5
    
    return min(100, urgency)

def extract_datetime(text):
    """Витягує дату/час з тексту"""
    import re
    from datetime import datetime
    
    # Шукаємо час у форматі HH:MM
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    if time_match:
        hour, minute = time_match.groups()
        now = datetime.now()
        return now.replace(hour=int(hour), minute=int(minute)).isoformat()
    
    return 'unknown'

def redact_sensitive_info(text):
    """Видаляє чутливу інформацію"""
    import re
    
    redacted = False
    reason = ""
    
    # Видаляємо координати
    if re.search(r'\d+\.\d+[,\s]+\d+\.\d+', text):
        text = re.sub(r'\d+\.\d+[,\s]+\d+\.\d+', '[координати видалено]', text)
        redacted = True
        reason = "координати"
    
    # Видаляємо технічні деталі
    sensitive_keywords = ['схема', 'інструкція', 'модифікація', 'виробництво', 'позиція ппо']
    for keyword in sensitive_keywords:
        if keyword in text.lower():
            redacted = True
            reason = "технічні деталі"
            break
    
    return text, redacted, reason

def generate_hash(category, city, datetime_str, text):
    """Генерує хеш для дедуплікації"""
    key = f"{category}_{city}_{datetime_str[:13]}_{text[:50]}"  # Година, перші 50 символів
    return hashlib.md5(key.encode()).hexdigest()

def analyze_post(text, channel_name):
    """Головна функція аналізу"""
    
    # Перевірка на спам/нерелевантне
    spam_keywords = ['реклама', 'продам', 'куплю', 'вакансія', 'розпродаж']
    if any(kw in text.lower() for kw in spam_keywords):
        return {'category': 'NOT_RELEVANT', 'action_recommendation': 'NO_ACTION'}
    
    # Визначення категорії
    category = categorize_threat(text)
    if category == 'NOT_RELEVANT':
        return {'category': 'NOT_RELEVANT', 'action_recommendation': 'NO_ACTION'}
    
    # Витягування даних
    location = extract_location(text)
    event_datetime = extract_datetime(text)
    urgency = calculate_urgency(text, category)
    
    # Редакція
    safe_text, redacted, redaction_reason = redact_sensitive_info(text)
    
    # Формування резюме
    summary = generate_summary(category, location, safe_text, urgency)
    
    # Теги
    tags = generate_tags(category, location['city'])
    
    # Рекомендація
    action = determine_action(urgency, channel_name, category)
    
    # Хеш для дедуплікації
    content_hash = generate_hash(category, location['city'], event_datetime, text)
    
    # Надійність джерела
    source_reliability = 'official' if channel_name in OFFICIAL_CHANNELS else 'unverified'
    
    return {
        'category': category,
        'region': location['region'],
        'city': location['city'],
        'event_datetime': event_datetime,
        'posted_datetime': datetime.now().isoformat(),
        'urgency': urgency,
        'safe_summary': summary,
        'tags': tags,
        'action_recommendation': action,
        'source_channel': channel_name,
        'source_reliability': source_reliability,
        'redacted': redacted,
        'redaction_reason': redaction_reason,
        'content_hash': content_hash
    }

def generate_summary(category, location, text, urgency):
    """Генерує короткий опис для публікації"""
    prefix = '[URGENT] ' if urgency > 70 else ''
    
    city = location['city'] if location['city'] != 'unknown' else location['region']
    
    category_names = {
        'UAV_THREAT': 'загроза БПЛА',
        'MISSILE_THREAT': 'загроза ракет',
        'KAB_FAB_THREAT': 'загроза КАБ/ФАБ',
        'AIR_ALERT': 'повітряна тривога',
        'EXPLOSION': 'вибухи',
        'UAV_SIGHTING': 'спостереження БПЛА',
        'ALL_CLEAR': 'відбій тривоги'
    }
    
    threat_type = category_names.get(category, 'інформація')
    
    # Обрізаємо текст до ключової інформації
    summary = f"{prefix}{city} — {threat_type}"
    
    # Додаємо ключову інфу з тексту (до 280 символів)
    important_parts = []
    if 'рух' in text.lower():
        important_parts.append('активний рух')
    if 'напрямок' in text.lower() or 'курс' in text.lower():
        important_parts.append('відомий напрямок')
    if 'ппо' in text.lower():
        important_parts.append('ППО працює')
    
    if important_parts:
        summary += '. ' + ', '.join(important_parts).capitalize()
    
    summary += '. Залишайтесь в укритті!' if urgency > 70 else '.'
    
    return summary[:280]

def generate_tags(category, city):
    """Генерує теги"""
    tags = []
    
    if category == 'UAV_THREAT' or category == 'UAV_SIGHTING':
        tags.append('uav')
    if category == 'MISSILE_THREAT':
        tags.append('missile')
    if category == 'KAB_FAB_THREAT':
        tags.append('bomb')
    
    if city != 'unknown':
        tags.append(city.lower().replace(' ', '_'))
    
    tags.append('ukraine')
    
    return tags

def determine_action(urgency, channel_name, category):
    """Визначає дію"""
    if category == 'NOT_RELEVANT':
        return 'NO_ACTION'
    
    if urgency >= 80:
        return 'ALERT_NOW'
    elif urgency >= 60:
        return 'ALERT_ADMIN' if channel_name not in OFFICIAL_CHANNELS else 'ALERT_NOW'
    elif urgency >= 40:
        return 'MONITOR'
    else:
        return 'NO_ACTION'

# ============= TELEGRAM КЛІЄНТ =============

class ThreatMonitor:
    def __init__(self):
        self.client = TelegramClient('monitor_session', API_ID, API_HASH)
        self.cache = set()  # Кеш хешів за останню годину
        self.last_cleanup = datetime.now()
    
    async def start(self):
        await self.client.start()
        print("✅ Клієнт запущено")
        
        # Підписуємося на канали
        for channel in ALL_CHANNELS:
            try:
                await self.client.get_entity(channel)
                print(f"📡 Моніторинг: {channel}")
            except Exception as e:
                print(f"❌ Не вдалося підключитись до {channel}: {e}")
        
        # Обробка нових повідомлень
        @self.client.on(events.NewMessage(chats=ALL_CHANNELS))
        async def handler(event):
            await self.process_message(event)
        
        print("🚀 Моніторинг активний")
        await self.client.run_until_disconnected()
    
    async def process_message(self, event):
        """Обробка вхідного повідомлення"""
        text = event.message.message
        if not text or len(text) < 20:
            return
        
        channel = await event.get_chat()
        channel_name = channel.username or str(channel.id)
        
        # Аналіз
        result = analyze_post(text, channel_name)
        
        # Перевірка дубліката
        if result['content_hash'] in self.cache:
            print(f"⏭️  Дублікат: {result['content_hash'][:8]}")
            return
        
        # Додаємо в кеш
        self.cache.add(result['content_hash'])
        
        # Очищення старого кешу (кожні 30 хв)
        if (datetime.now() - self.last_cleanup).seconds > 1800:
            self.cache.clear()
            self.last_cleanup = datetime.now()
        
        # Дії
        if result['action_recommendation'] == 'ALERT_NOW':
            await self.publish_alert(result)
        elif result['action_recommendation'] == 'ALERT_ADMIN':
            await self.notify_admin(result)
        elif result['action_recommendation'] == 'MONITOR':
            await self.log_to_database(result)
        
        print(f"📊 {result['category']} | {result['city']} | Urgency: {result['urgency']}")
    
    async def publish_alert(self, result):
        """Публікація в канал"""
        message = f"🚨 {result['safe_summary']}\n\n"
        message += f"📍 Регіон: {result['region']}\n"
        message += f"🕐 Час: {datetime.now().strftime('%H:%M')}\n"
        message += f"📡 Джерело: {result['source_reliability']}\n"
        message += f"#{'#'.join(result['tags'])}"
        
        # Відправка через бота
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TARGET_CHANNEL,
            'text': message,
            'parse_mode': 'HTML'
        }
        requests.post(url, json=data)
        print(f"✅ Опубліковано: {result['city']}")
    
    async def notify_admin(self, result):
        """Повідомлення адміністратора"""
        # Відправка адміну для перевірки перед публікацією
        admin_id = os.getenv('ADMIN_TELEGRAM_ID')
        if admin_id:
            message = f"⚠️ ПЕРЕВІРИТИ:\n{json.dumps(result, ensure_ascii=False, indent=2)}"
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {'chat_id': admin_id, 'text': message[:4000]}
            requests.post(url, json=data)
    
    async def log_to_database(self, result):
        """Зберігання в БД (GitHub Issues або JSON)"""
        # Додавання в файл JSON
        log_file = 'alerts_log.json'
        try:
            with open(log_file, 'r') as f:
                logs = json.load(f)
        except:
            logs = []
        
        logs.append(result)
        
        # Зберігаємо тільки за останні 24 години
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        logs = [log for log in logs if log['posted_datetime'] > cutoff]
        
        with open(log_file, 'w') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

# ============= ЗАПУСК =============
if __name__ == '__main__':
    monitor = ThreatMonitor()
    asyncio.run(monitor.start())
