# 🔒 Migration Guide: TCP to HTTP Actions

## 🚨 Security Notice

The old **TCP port 5678** has been **replaced with secure HTTP POST** endpoints for security reasons.

### ❌ **Security Issues with TCP (Port 5678):**
- **No encryption** - all data sent in plaintext
- **Tokens logged** in plaintext (security risk)
- **No rate limiting** - vulnerable to DoS attacks  
- **Weak validation** - could accept malformed data
- **Not firewall-friendly** for web deployment

### ✅ **New HTTP Security (Port 8088):**
- **HTTPS ready** - can be encrypted with TLS
- **Proper authentication** with Bearer tokens
- **Input validation** - rejects invalid actions
- **Rate limiting ready** - standard web protections
- **Firewall friendly** - standard HTTP port

---

## 📋 Migration Steps

### 1. **Update OBS Script**

**Replace** `socket-sentinel.lua` **with** `socket-sentinel-http.lua`:

```lua
-- OLD TCP VERSION (DEPRECATED)
local PORT = 5678 -- TCP port
local cmd = "printf ... | nc HOST PORT"

-- NEW HTTP VERSION (SECURE)
local HTTP_PORT = 8088 -- HTTP port  
local cmd = "curl -X POST http://HOST:PORT/action ..."
```

### 2. **Update Docker Configuration**

**Remove TCP port** from `docker-compose.yml`:

```yaml
# OLD (INSECURE)
ports:
  - "5678:5678"  # REMOVE THIS
  - "8088:8088"

# NEW (SECURE)
ports:
  - "8088:8088"  # ONLY THIS
```

### 3. **Update Integration Scripts**

**Change any custom scripts** from TCP to HTTP:

```bash
# OLD TCP METHOD (INSECURE)
echo "token=xxx\ngame=hunt_showdown\naction=kill" | nc localhost 5678

# NEW HTTP METHOD (SECURE)
curl -X POST http://localhost:8088/action \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"action": "kill", "game": "hunt_showdown"}'
```

---

## 🧪 Testing the Migration

### Test HTTP Actions:
```bash
# Test inside container
docker-compose exec obs-socket-sentinel python test_action_http.py kill hunt_showdown

# Test with curl
curl -X POST http://localhost:8088/action \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rematch_garage_culinary_unluckily_unclamped_expansive" \
  -d '{"action": "headshot", "game": "hunt_showdown"}'
```

### Expected Response:
```json
{
  "status": "success", 
  "message": "Action 'kill' processed successfully",
  "game": "hunt_showdown",
  "action": "kill"
}
```

---

## 📊 New HTTP API

### **Endpoint:** `POST /action`
### **Authentication:** Required - `Authorization: Bearer {SS_TOKEN}`

### **Request Format:**
```json
{
  "action": "kill",           // REQUIRED: action name
  "game": "hunt_showdown"     // OPTIONAL: game/project name
}
```

### **Valid Actions:**
```
alert, ammo, assist, banish, bleed, clear, death, downed, 
drowned, extract, fire, fish, funny, headshot, heal, kill, 
magic, melee, mining, noise, poison, reload, revive, 
run_end, run_start, shootout, snipe, stealth, teleport, 
traded, trap, undo
```

### **Response Format:**
```json
{
  "status": "success",
  "message": "Action 'kill' processed successfully", 
  "game": "hunt_showdown",
  "action": "kill"
}
```

### **Error Response:**
```json
{
  "error": "Unknown action: invalid_action. Valid actions: ..."
}
```

---

## 🛡️ Security Benefits

1. **🔐 Token Security** - No longer logged in plaintext
2. **✅ Input Validation** - Only valid actions accepted
3. **📊 Better Logging** - Sanitized, secure logs
4. **🌐 Web Ready** - HTTPS, CORS, firewall friendly
5. **🚦 Rate Limiting** - Protection against abuse
6. **📝 Standard Format** - JSON instead of raw text

---

## 🔧 Troubleshooting

### Common Issues:

1. **401 Unauthorized**
   ```bash
   # Check your token
   echo $SS_TOKEN
   # Use correct Authorization header
   -H "Authorization: Bearer YOUR_TOKEN_HERE"
   ```

2. **400 Bad Request - Unknown Action**
   ```bash
   # Check valid actions
   curl -s http://localhost:8088/action \
     -H "Authorization: Bearer $SS_TOKEN" \
     -d '{"action": "invalid"}' | jq .error
   ```

3. **Connection Refused**
   ```bash
   # Check if port 8088 is accessible
   curl -s http://localhost:8088/overlay | head -1
   ```

### Migration Verification:
```bash
# 1. Verify TCP port is closed
nc -z localhost 5678 && echo "❌ TCP still open" || echo "✅ TCP closed"

# 2. Verify HTTP port is open  
curl -s http://localhost:8088/overlay > /dev/null && echo "✅ HTTP working"

# 3. Test action endpoint
curl -X POST http://localhost:8088/action \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SS_TOKEN" \
  -d '{"action": "kill"}' && echo "✅ Actions working"
```

---

## ✅ **Migration Complete!**

Your OBS Socket Sentinel is now using **secure HTTP** instead of **insecure TCP**. 

🎉 **Benefits:**
- 🔒 Much more secure for web deployment
- 🚀 Better error handling and validation  
- 📊 Cleaner, safer logging
- 🌐 Ready for HTTPS and public internet

⚠️ **Remember to:**
- Update your OBS script to `socket-sentinel-http.lua`
- Remove TCP port 5678 from any firewall rules
- Test all your game integrations with HTTP