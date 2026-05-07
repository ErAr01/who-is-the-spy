# DigitalOcean Cloud Firewall — Вариант В

Инструкция по настройке защиты observability-стека через DigitalOcean Cloud Firewall с IP-whitelist.

---

## 📌 Когда использовать Вариант В

**Плюсы:**
- ✅ Простая настройка через веб-интерфейс DigitalOcean
- ✅ Не требует изменений в docker-compose.yml
- ✅ Защита на уровне сетевой инфраструктуры (до попадания на сервер)
- ✅ Легко добавлять/удалять IP через GUI

**Минусы:**
- ❌ Привязка к провайдеру (vendor lock-in)
- ❌ Неудобно для динамических IP (домашний интернет без статики)
- ❌ Нужно обновлять whitelist при смене IP

**Recommended use case:**
- Временное решение для быстрого запуска
- Администратор работает с фиксированного IP (офис, VPN)
- Нет возможности настроить Nginx или SSH-туннель

---

## 🚀 Быстрый старт

### 1. Определение вашего публичного IP

```bash
# На локальной машине
curl ifconfig.me
# Пример вывода: 203.0.113.42
```

Сохраните этот IP — он потребуется для whitelist.

### 2. Создание Cloud Firewall в DigitalOcean

1. Перейдите в веб-интерфейс DigitalOcean
2. **Networking → Firewalls → Create Firewall**
3. Название: `who-is-the-spy-observability-fw`
4. Описание: `Security for observability stack (Grafana, Prometheus, Loki, Redis)`

### 3. Настройка Inbound Rules

#### SSH (обязательно!)

```
Type: SSH
Protocol: TCP
Port Range: 22
Sources: All IPv4, All IPv6
```

⚠️ **ВАЖНО:** НЕ ограничивайте SSH только вашим IP! Если ваш IP изменится, вы потеряете доступ к серверу.

#### Grafana

```
Type: Custom
Protocol: TCP
Port Range: 3000
Sources: <ВАШ_IP>/32
```

Пример: `203.0.113.42/32`

#### Prometheus

```
Type: Custom
Protocol: TCP
Port Range: 9090
Sources: <ВАШ_IP>/32
```

#### Loki

```
Type: Custom
Protocol: TCP
Port Range: 3100
Sources: <ВАШ_IP>/32
```

#### Redis

```
НЕ добавляйте правило для порта 6379!
Redis должен быть заблокирован публично.
```

Если Redis нужен извне (не рекомендуется):
```
Type: Custom
Protocol: TCP
Port Range: 6379
Sources: <ВАШ_IP>/32
```

### 4. Настройка Outbound Rules (по умолчанию)

```
Protocol: ICMP
Destinations: All IPv4, All IPv6

Protocol: TCP
Ports: All
Destinations: All IPv4, All IPv6

Protocol: UDP
Ports: All
Destinations: All IPv4, All IPv6
```

Не меняйте эти правила — они нужны для исходящих подключений (apt, docker pull, API запросы).

### 5. Применить к Droplet

В разделе **Apply to Droplets** выберите ваш сервер с Who Is The Spy.

### 6. Проверка правил

**С вашего IP (должно работать):**

```bash
curl http://<PUBLIC_IP>:3000/api/health
# {"database":"ok"}

curl http://<PUBLIC_IP>:9090/-/ready
# Prometheus is Ready.
```

**С другого IP (используйте VPN или мобильный интернет):**

```bash
curl --max-time 5 http://<PUBLIC_IP>:3000
# curl: (28) Connection timed out
```

---

## 🔧 Управление IP-whitelist

### Добавление нового IP (через веб-интерфейс)

1. Перейдите в **Networking → Firewalls → who-is-the-spy-observability-fw**
2. В секции **Inbound Rules** найдите правила для портов 3000, 9090, 3100
3. Нажмите **Edit** на каждом правиле
4. Добавьте новый IP в поле **Sources**
5. Нажмите **Save**

### Удаление старого IP (через веб-интерфейс)

1. Откройте правило для редактирования
2. Удалите старый IP из списка Sources
3. Сохраните изменения

### Автоматизация через DigitalOcean API

#### Получение API токена

1. Перейдите в **API → Tokens/Keys**
2. **Generate New Token**
3. Название: `firewall-management`
4. Scopes: `Read + Write`
5. Сохраните токен в безопасном месте

#### Скрипт автообновления IP

Создайте скрипт `/root/update-firewall-ip.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Конфигурация
FIREWALL_ID="ваш-firewall-id"  # Найдите в URL веб-интерфейса
DO_TOKEN="ваш-do-api-token"
CURRENT_IP=$(curl -s ifconfig.me)

echo "Текущий IP: $CURRENT_IP"

# Получение текущих правил
CURRENT_RULES=$(curl -s -X GET \
  "https://api.digitalocean.com/v2/firewalls/$FIREWALL_ID" \
  -H "Authorization: Bearer $DO_TOKEN" \
  | jq -r '.firewall.inbound_rules')

echo "Обновление правил для Grafana, Prometheus, Loki..."

# Обновление правил (замена старых IP на новый)
curl -s -X PUT \
  "https://api.digitalocean.com/v2/firewalls/$FIREWALL_ID" \
  -H "Authorization: Bearer $DO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inbound_rules": [
      {
        "protocol": "tcp",
        "ports": "22",
        "sources": {
          "addresses": ["0.0.0.0/0", "::/0"]
        }
      },
      {
        "protocol": "tcp",
        "ports": "3000",
        "sources": {
          "addresses": ["'$CURRENT_IP'/32"]
        }
      },
      {
        "protocol": "tcp",
        "ports": "9090",
        "sources": {
          "addresses": ["'$CURRENT_IP'/32"]
        }
      },
      {
        "protocol": "tcp",
        "ports": "3100",
        "sources": {
          "addresses": ["'$CURRENT_IP'/32"]
        }
      }
    ]
  }'

echo "✅ Firewall обновлен для IP: $CURRENT_IP"
```

**Использование:**

```bash
chmod +x /root/update-firewall-ip.sh
bash /root/update-firewall-ip.sh
```

#### Поиск Firewall ID

```bash
# Через API
curl -X GET "https://api.digitalocean.com/v2/firewalls" \
  -H "Authorization: Bearer $DO_TOKEN" \
  | jq -r '.firewalls[] | select(.name=="who-is-the-spy-observability-fw") | .id'

# Через веб-интерфейс
# URL: https://cloud.digitalocean.com/networking/firewalls/<FIREWALL_ID>
```

---

## 🔒 Дополнительная защита: UFW на сервере

Cloud Firewall работает на уровне инфраструктуры DigitalOcean. Для дублирования защиты на уровне ОС используйте UFW:

```bash
# На сервере
sudo bash deploy/ufw/ufw-setup-variant-c.sh
```

Этот скрипт:
- Настроит UFW с теми же правилами, что и Cloud Firewall
- Обеспечит защиту даже при случайном отключении Cloud Firewall
- Добавит дополнительный уровень безопасности

**Архитектура защиты:**

```
Интернет
   ↓
[DigitalOcean Cloud Firewall] ← Блокирует на уровне сети DO
   ↓
[UFW на сервере] ← Блокирует на уровне ОС Ubuntu
   ↓
[Docker Network] ← Изоляция контейнеров
   ↓
[Grafana/Prometheus/Loki]
```

---

## 📊 Мониторинг блокированных запросов

### Просмотр логов Cloud Firewall

К сожалению, DigitalOcean Cloud Firewall **не предоставляет логи** заблокированных запросов.

**Альтернативы для мониторинга:**

1. **UFW логи на сервере:**

```bash
# Включить логирование UFW
sudo ufw logging on

# Просмотр логов
sudo tail -f /var/log/ufw.log

# Фильтрация заблокированных запросов на observability-порты
sudo grep "DPT=3000\|DPT=9090\|DPT=3100\|DPT=6379" /var/log/ufw.log | grep BLOCK
```

2. **Nginx Access Logs (если используется Nginx в дополнение):**

```bash
docker compose logs nginx | grep "401\|403"
```

3. **Prometheus Metrics для Redis:**

Добавьте мониторинг неудачных подключений к Redis:

```yaml
# В deploy/observability/prometheus/rules/security-alerts.yml
- alert: UnauthorizedRedisConnections
  expr: rate(redis_rejected_connections_total[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Обнаружены попытки подключения к Redis"
    description: "{{ $value }} отклоненных подключений за последние 5 минут"
```

---

## 🚨 Сценарии использования

### Сценарий 1: Работа из дома (динамический IP)

**Проблема:** Домашний IP меняется каждые 24 часа при переподключении к провайдеру.

**Решение 1 — VPN с фиксированным IP:**

```bash
# Используйте VPN с фиксированным выходным IP
# Примеры: Mullvad, ProtonVPN, DigitalOcean VPN
# Добавьте IP VPN в whitelist один раз
```

**Решение 2 — Скрипт автообновления IP:**

```bash
# Настройте скрипт update-firewall-ip.sh (см. выше)
# Запускайте вручную при смене IP:
bash /root/update-firewall-ip.sh
```

**Решение 3 — SSH-туннель (переход на Вариант А):**

```bash
# Если частые смены IP — проще использовать SSH-туннель
# См. docs/SECURITY.md, Вариант А
```

### Сценарий 2: Работа из офиса (фиксированный IP)

**Оптимальный вариант:** Добавьте офисный IP в whitelist один раз.

```bash
# Определите офисный IP
curl ifconfig.me

# Добавьте в Cloud Firewall через веб-интерфейс
# Готово — доступ работает стабильно
```

### Сценарий 3: Командировка/путешествие

**Проблема:** Нужен доступ к Grafana из другого города/страны.

**Решение 1 — VPN до офиса:**

```bash
# Подключитесь к офисному VPN
# IP останется офисным, доступ сохранится
```

**Решение 2 — Временное добавление IP:**

```bash
# Определите текущий IP
curl ifconfig.me

# Добавьте через веб-интерфейс DigitalOcean
# Или используйте скрипт update-firewall-ip.sh

# После возвращения — удалите временный IP
```

**Решение 3 — SSH-туннель:**

```bash
# SSH обычно разрешен везде (порт 22)
ssh -L 3000:127.0.0.1:3000 root@<PUBLIC_IP>
# Откройте http://localhost:3000
```

### Сценарий 4: Доступ для всей команды

**Проблема:** 5-10 разработчиков с разными IP.

**Решение 1 — Офисный VPN:**

```bash
# Настройте VPN с фиксированным выходным IP
# Вся команда подключается через VPN
# В whitelist добавлен только один IP
```

**Решение 2 — Whitelist для каждого:**

```bash
# Соберите IP всех членов команды
# Добавьте все IP в Cloud Firewall:
203.0.113.42/32  # Developer 1
203.0.113.43/32  # Developer 2
203.0.113.44/32  # Developer 3
# ... и т.д.
```

**Решение 3 — Переход на Вариант Б (Nginx):**

```bash
# Для команды проще использовать Nginx с Basic Auth
# Доступ через https://grafana.example.com
# Пароли раздаются через htpasswd
# См. docs/SECURITY.md, Вариант Б
```

---

## ⚠️ Важные ограничения

### 1. Cloud Firewall применяется НЕ мгновенно

После изменения правил требуется **30-60 секунд** для применения на всех узлах DigitalOcean.

```bash
# Если изменения не работают сразу — подождите минуту
sleep 60
curl http://<PUBLIC_IP>:3000
```

### 2. IPv6 также нужно учитывать

Если ваш провайдер поддерживает IPv6:

```bash
# Определить IPv6
curl -6 ifconfig.me

# Добавить в whitelist
2001:db8::1/128
```

### 3. Максимальное количество правил

DigitalOcean ограничивает количество правил на один firewall:

- **Inbound rules:** до 50
- **Outbound rules:** до 50

Если нужно больше — создайте несколько firewall'ов или переходите на Вариант Б.

### 4. Cloud Firewall НЕ защищает от DDoS уровня приложения

Cloud Firewall блокирует только сетевой трафик. Для защиты от L7 DDoS используйте:
- Cloudflare (перед Nginx)
- Rate limiting в Nginx
- Fail2Ban

---

## 📋 Чеклист после настройки

- [ ] Cloud Firewall создан и применен к Droplet
- [ ] SSH (порт 22) разрешен для All IPv4/IPv6
- [ ] Observability-порты (3000, 9090, 3100) разрешены только для вашего IP
- [ ] Redis (порт 6379) НЕ добавлен в правила (заблокирован)
- [ ] UFW настроен на сервере для дублирования защиты
- [ ] Проверка доступа с вашего IP — работает
- [ ] Проверка доступа с другого IP (VPN) — заблокирован
- [ ] Скрипт update-firewall-ip.sh настроен (опционально)
- [ ] Команда знает, как добавлять свои IP (если применимо)

---

## 📖 Дополнительные ресурсы

- **[DigitalOcean Cloud Firewalls Docs](https://docs.digitalocean.com/products/networking/firewalls/)** — Официальная документация
- **[DigitalOcean API Docs](https://docs.digitalocean.com/reference/api/api-reference/#tag/Firewalls)** — API для автоматизации
- **[docs/SECURITY.md](../../docs/SECURITY.md)** — Сравнение всех вариантов защиты
- **[deploy/ufw/ufw-setup-variant-c.sh](../ufw/ufw-setup-variant-c.sh)** — Скрипт настройки UFW для Варианта В

---

**Дата обновления:** 2026-05-07  
**Совместимость:** DigitalOcean Cloud Firewalls (все регионы)
