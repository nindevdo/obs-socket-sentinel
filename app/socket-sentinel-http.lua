-- socket-sentinel-http.lua  
-- OBS Lua script: send hotkey events over HTTP POST (secure replacement for TCP)
-- Fetch YAML config from http://HOST:HTTP_PORT/config
-- Per-game hotkeys and scene-based gating.

local obs = obslua

----------------------------------------------------
-- CONFIG DEFAULTS
----------------------------------------------------

local HOST = "127.0.0.1" -- HTTP hostname
local HTTP_PORT = 8088 -- HTTP port for both actions and config
local SS_TOKEN = "" -- Security token for authentication

local GAMES = {} -- populated from YAML
local hotkey_ids = {} -- [game][action] = id

----------------------------------------------------
-- LOGGING
----------------------------------------------------

function log_info(msg)
	print("[INFO] " .. tostring(msg))
	obs.blog(obs.LOG_INFO, "[Socket Sentinel] " .. tostring(msg))
end

function log_error(msg)
	print("[ERROR] " .. tostring(msg))
	obs.blog(obs.LOG_ERROR, "[Socket Sentinel] " .. tostring(msg))
end

----------------------------------------------------
-- HTTP CLIENT
----------------------------------------------------

function shell_escape(str)
	return "'" .. string.gsub(str, "'", "'\"'\"'") .. "'"
end

function send_http_action(game_key, action_name)
	-- Prepare JSON payload
	local json_payload = string.format('{"action": "%s", "game": "%s"}', action_name, tostring(game_key))
	
	-- Prepare curl command with proper authentication
	local auth_header = ""
	if SS_TOKEN and SS_TOKEN ~= "" then
		auth_header = string.format("-H 'Authorization: Bearer %s'", SS_TOKEN)
	end
	
	local cmd = string.format(
		"curl -s -X POST http://%s:%d/action -H 'Content-Type: application/json' %s -d %s >/dev/null 2>&1 &",
		HOST, HTTP_PORT, auth_header, shell_escape(json_payload)
	)

	log_info("Executing: " .. cmd)
	os.execute(cmd)
	log_info(
		string.format("Sent HTTP action: game=%s action=%s → %s:%d/action", tostring(game_key), action_name, HOST, HTTP_PORT)
	)
end

----------------------------------------------------
-- HOTKEY CALLBACK
----------------------------------------------------

function hotkey_callback(game_key, action_name)
	return function(pressed)
		if not pressed then
			return
		end

		-- Scene-based gating
		local current_scene_name = obs.obs_frontend_get_current_scene_name()
		if not current_scene_name then
			log_info("No current scene detected, skipping action")
			return
		end

		local game_config = GAMES[game_key]
		if not game_config then
			log_error(string.format("Game config missing for key: %s", game_key))
			return
		end

		local allowed_scenes = game_config.scenes
		if allowed_scenes and #allowed_scenes > 0 then
			local scene_allowed = false
			for _, scene_name in ipairs(allowed_scenes) do
				if current_scene_name == scene_name then
					scene_allowed = true
					break
				end
			end

			if not scene_allowed then
				log_info(
					string.format(
						"Scene gating: current='%s' not in allowed scenes %s for game=%s",
						current_scene_name,
						table.concat(allowed_scenes, ", "),
						game_key
					)
				)
				return
			end
		end

		log_info(
			string.format("Action triggered: %s.%s (scene: %s)", game_key, action_name, current_scene_name)
		)

		-- Send HTTP action
		send_http_action(game_key, action_name)
	end
end

----------------------------------------------------
-- HTTP GET utility
----------------------------------------------------

function http_get(host, port, path, token)
	local auth_header = ""
	if token and token ~= "" then
		auth_header = string.format("-H 'Authorization: Bearer %s'", token)
	end
	
	local cmd = string.format(
		"curl -s http://%s:%d%s %s",
		host, port, path, auth_header
	)
	
	local handle = io.popen(cmd)
	if not handle then
		log_error("Failed to execute curl command")
		return nil
	end
	
	local data = handle:read("*a")
	handle:close()
	return data
end

local function load_yaml_from_server()
	log_info(string.format("Fetching YAML from http://%s:%d/config ...", HOST, HTTP_PORT))
	local text = http_get(HOST, HTTP_PORT, "/config", SS_TOKEN)
	if not text or text == "" then
		log_error("YAML fetch failed or empty. Check token and server connectivity.")
		return nil
	end
	return text
end

----------------------------------------------------
-- YAML PARSER (simplified)
----------------------------------------------------

local function parse_yaml(yaml_text)
	local games = {}
	local current_game = nil
	local in_actions = false
	local in_scenes = false

	for line in yaml_text:gmatch("[^\r\n]+") do
		line = line:gsub("^%s+", ""):gsub("%s+$", "") -- trim
		
		if line == "" or line:match("^#") then
			-- skip empty/comment lines
		elseif line:match("^(%w+):$") then
			-- top-level game key
			current_game = line:match("^(%w+):$")
			games[current_game] = { actions = {}, scenes = {} }
			in_actions = false
			in_scenes = false
			log_info("Found game: " .. current_game)
		elseif line == "actions:" and current_game then
			in_actions = true
			in_scenes = false
		elseif line == "scenes:" and current_game then
			in_actions = false
			in_scenes = true
		elseif in_actions and current_game and line:match("^%- (.+)$") then
			local action = line:match("^%- (.+)$")
			table.insert(games[current_game].actions, action)
		elseif in_scenes and current_game and line:match("^%- (.+)$") then
			local scene = line:match("^%- (.+)$")
			table.insert(games[current_game].scenes, scene)
		end
	end

	return games
end

----------------------------------------------------
-- HOTKEY MANAGEMENT
----------------------------------------------------

local function clear_hotkeys()
	for game_key, actions_map in pairs(hotkey_ids) do
		for action_name, hotkey_id in pairs(actions_map) do
			obs.obs_hotkey_unregister(hotkey_id)
			log_info(string.format("Unregistered hotkey: %s.%s", game_key, action_name))
		end
	end
	hotkey_ids = {}
end

local function register_hotkeys()
	clear_hotkeys()

	for game_key, game_config in pairs(GAMES) do
		hotkey_ids[game_key] = {}
		for _, action_name in ipairs(game_config.actions or {}) do
			local hotkey_name = string.format("%s.%s", game_key, action_name)
			local hotkey_desc = string.format("[%s] %s", game_key, action_name)

			local hotkey_id = obs.obs_hotkey_register_frontend(
				hotkey_name,
				hotkey_desc,
				hotkey_callback(game_key, action_name)
			)

			hotkey_ids[game_key][action_name] = hotkey_id
			log_info(string.format("Registered hotkey: %s → %s", hotkey_name, hotkey_desc))
		end
	end
end

local function refresh_config()
	log_info("🔄 Refreshing configuration from server...")
	local yaml_text = load_yaml_from_server()
	if not yaml_text then
		log_error("Failed to load YAML from server")
		return
	end

	local new_games = parse_yaml(yaml_text)
	GAMES = new_games

	log_info(string.format("Loaded %d games from server", table_length(GAMES)))
	for game_key, game_config in pairs(GAMES) do
		log_info(
			string.format(
				"  %s: %d actions, %d scenes",
				game_key,
				#(game_config.actions or {}),
				#(game_config.scenes or {})
			)
		)
	end

	register_hotkeys()
	log_info("✅ Configuration refresh complete")
end

function table_length(t)
	local count = 0
	for _ in pairs(t) do
		count = count + 1
	end
	return count
end

----------------------------------------------------
-- OBS INTEGRATION
----------------------------------------------------

function script_description()
	return [[
<h2>Socket Sentinel HTTP Client</h2>
<p>Secure HTTP-based replacement for TCP socket communication.</p>
<p><strong>Features:</strong></p>
<ul>
<li>🔒 Secure HTTP POST with authentication</li>
<li>⚡ Real-time game action tracking</li>
<li>🎯 Scene-based action gating</li>
<li>🔄 Dynamic config loading</li>
</ul>
<p><strong>Setup:</strong></p>
<ol>
<li>Enter your server host/port and authentication token</li>
<li>Click "Refresh Config" to load game configurations</li>
<li>Assign hotkeys to your game actions</li>
</ol>
]]
end

function script_properties()
	local props = obs.obs_properties_create()
	
	obs.obs_properties_add_text(props, "host", "Server Host", obs.OBS_TEXT_DEFAULT)
	obs.obs_properties_add_int(props, "http_port", "HTTP Port", 1, 65535, 1)
	obs.obs_properties_add_text(props, "ss_token", "Authentication Token", obs.OBS_TEXT_PASSWORD)
	
	obs.obs_properties_add_button(props, "refresh_config", "🔄 Refresh Config", function()
		refresh_config()
		return true
	end)
	
	return props
end

function script_defaults(settings)
	obs.obs_data_set_default_string(settings, "host", HOST)
	obs.obs_data_set_default_int(settings, "http_port", HTTP_PORT)
	obs.obs_data_set_default_string(settings, "ss_token", SS_TOKEN)
end

function script_update(settings)
	HOST = obs.obs_data_get_string(settings, "host") or "127.0.0.1"

	HTTP_PORT = obs.obs_data_get_int(settings, "http_port")
	if HTTP_PORT < 1 then
		HTTP_PORT = 8088
	end

	SS_TOKEN = obs.obs_data_get_string(settings, "ss_token") or ""

	log_info(string.format("Updated settings → HTTP=%s:%d Token=%s", HOST, HTTP_PORT, 
		SS_TOKEN ~= "" and "***SET***" or "NOT_SET"))
end

function script_load(settings)
	script_update(settings)
	
	log_info("🚀 Socket Sentinel HTTP Client loaded")
	log_info("📡 Using secure HTTP POST instead of insecure TCP")
	log_info("🔒 Authentication: " .. (SS_TOKEN ~= "" and "Enabled" or "⚠️  DISABLED"))
	
	-- Auto-load config on startup
	refresh_config()
end

function script_unload()
	clear_hotkeys()
	log_info("Socket Sentinel HTTP Client unloaded")
end