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

local function log_info(msg)
	obs.script_log(obs.LOG_INFO, "[socket-sentinel-http] " .. msg)
end

local function log_error(msg)
	obs.script_log(obs.LOG_ERROR, "[socket-sentinel-http] " .. msg)
end

local function log_warn(msg)
	obs.script_log(obs.LOG_WARNING, "[socket-sentinel-http] " .. msg)
end

----------------------------------------------------
-- STRING / NAME NORMALIZERS
----------------------------------------------------

local function trim(s)
	if s == nil then
		return ""
	end
	return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function strip_comment(line)
	local in_quote = false
	local out = {}
	for i = 1, #line do
		local ch = line:sub(i, i)
		if ch == '"' or ch == "'" then
			in_quote = not in_quote
		elseif ch == "#" and not in_quote then
			break
		end
		table.insert(out, ch)
	end
	return table.concat(out)
end

local function indent_level(s)
	local _, spaces = s:find("^[ ]*")
	return spaces or 0
end

-- Normalize both scene names and game keys
local function normalize_name(s)
	s = trim(s or "")
	s = s:lower()
	s = s:gsub("%s+", "_")
	return s
end

----------------------------------------------------
-- SHELL ESCAPE
----------------------------------------------------

local function shell_escape(s)
	if s == nil then
		s = ""
	end
	return "'" .. string.gsub(s, "'", "'\"'\"'") .. "'"
end

----------------------------------------------------
-- CURRENT SCENE NAME
----------------------------------------------------

local function get_current_scene_name()
	local src = obs.obs_frontend_get_current_scene()
	if not src then
		return nil
	end
	local name = obs.obs_source_get_name(src)
	obs.obs_source_release(src)
	return name
end

----------------------------------------------------
-- HTTP ACTION SEND VIA CURL
----------------------------------------------------
local function send_http_action(game_key, action_name)
	if not action_name or action_name == "" then
		return
	end

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
local function make_hotkey_callback(game_key, action_name)
	return function(pressed)
		if not pressed then
			return
		end

		local scene_name = get_current_scene_name()
		if not scene_name then
			return
		end

		local scene = normalize_name(scene_name)
		local game = normalize_name(game_key)

		-- System actions (undo, clear, start) work globally regardless of scene
		local system_actions = {undo = true, clear = true, start = true}
		
		if not system_actions[action_name] then
			-- Scene gating: only fire when this game matches the current scene for regular actions
			if scene ~= game then
				log_info(
					string.format(
						"Ignoring [%s:%s] because scene '%s' != game '%s'",
						game_key,
						action_name,
						scene_name,
						game_key
					)
				)
				return
			end
		end

		log_info(
			string.format("Hotkey triggered → game=%s action=%s (scene '%s')", game_key, action_name, scene_name)
		)

		-- send both game and action via HTTP
		send_http_action(game_key, action_name)
	end
end

----------------------------------------------------
-- FETCH YAML FROM PYTHON /config
----------------------------------------------------

local function http_get(host, port, path, token)
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
-- MINIMAL YAML PARSER FOR games.*.actions (COPIED FROM WORKING VERSION)
----------------------------------------------------

local function load_games_from_yaml_text(yaml_text)
	local lines = {}
	for line in yaml_text:gmatch("[^\r\n]+") do
		table.insert(lines, line)
	end

	local games = {}
	local in_games = false
	local current_game = nil
	local in_actions = false

	for _, raw in ipairs(lines) do
		local line = strip_comment(raw)
		if line:match("^%s*$") then
			goto continue
		end

		local lvl = indent_level(line)
		local t = trim(line)

		if lvl == 0 and t == "games:" then
			in_games = true
			current_game = nil
			in_actions = false
			goto continue
		end

		if not in_games then
			goto continue
		end

		if lvl == 2 then
			local gkey = t:match("^([%w_]+):%s*$")
			if gkey then
				current_game = gkey
				games[current_game] = { actions = {} }
				in_actions = false
				log_info("Found game: " .. current_game)
			end
			goto continue
		end

		if not current_game then
			goto continue
		end

		if lvl == 4 and t == "actions:" then
			in_actions = true
			log_info("Found actions section for: " .. current_game)
			goto continue
		end

		if in_actions and lvl >= 6 then
			local akey = t:match("^([%w_]+)%s*:")
			if akey then
				table.insert(games[current_game].actions, akey)
				log_info("  Added action: " .. akey)
			end
		end

		::continue::
	end

	return games
end

local function init_games_from_server()
	local text = load_yaml_from_server()
	if not text then
		log_error("Could not load YAML — no hotkeys will be registered.")
		GAMES = {}
		return
	end

	local parsed = load_games_from_yaml_text(text)
	if not parsed or next(parsed) == nil then
		log_error("Parsed YAML but found no games.*.actions.")
		GAMES = {}
		return
	end

	GAMES = parsed
end

----------------------------------------------------
-- REGISTER HOTKEYS (COPIED FROM WORKING VERSION)
----------------------------------------------------

local function register_hotkeys()
	-- Don't clear existing hotkeys - preserve user's key mappings!
	-- Only register hotkeys that don't already exist
	
	-- Register game-specific actions
	for game_key, g in pairs(GAMES) do
		hotkey_ids[game_key] = hotkey_ids[game_key] or {}
		for _, action_name in ipairs(g.actions or {}) do
			-- Skip if hotkey already exists (preserve user mappings)
			if hotkey_ids[game_key][action_name] then
				log_info(string.format("Skipping existing hotkey: %s.%s", game_key, action_name))
				goto continue
			end
			
			local internal_id = "socket_sentinel_" .. game_key .. "_" .. action_name
			local label = string.format("Socket Sentinel [%s]: %s", game_key, action_name)

			local id = obs.obs_hotkey_register_frontend(internal_id, label, make_hotkey_callback(game_key, action_name))

			if id then
				hotkey_ids[game_key][action_name] = id
				log_info("Registered NEW hotkey: " .. label)
			else
				log_warn("Failed hotkey register: " .. internal_id)
			end
			
			::continue::
		end
	end
	
	-- Register system actions for the first game (they work globally)
	local first_game = next(GAMES)
	if first_game then
		hotkey_ids[first_game] = hotkey_ids[first_game] or {}
		local system_actions = {"undo", "clear", "start"}
		for _, action_name in ipairs(system_actions) do
			-- Skip if system hotkey already exists
			if hotkey_ids[first_game][action_name] then
				log_info(string.format("Skipping existing system hotkey: %s", action_name))
				goto continue_system
			end
			
			local internal_id = "socket_sentinel_system_" .. action_name
			local label = string.format("Socket Sentinel [SYSTEM]: %s", action_name)

			local id = obs.obs_hotkey_register_frontend(internal_id, label, make_hotkey_callback(first_game, action_name))

			if id then
				hotkey_ids[first_game][action_name] = id
				log_info("Registered NEW system hotkey: " .. label)
			else
				log_warn("Failed system hotkey register: " .. internal_id)
			end
			
			::continue_system::
		end
	end
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

local function cleanup_removed_hotkeys()
	-- Remove hotkeys for actions that no longer exist in the config
	-- But preserve hotkeys for actions that still exist
	
	for game_key, actions_map in pairs(hotkey_ids) do
		local game_config = GAMES[game_key]
		if not game_config then
			-- Entire game was removed from config
			log_info(string.format("Removing all hotkeys for removed game: %s", game_key))
			for action_name, hotkey_id in pairs(actions_map) do
				obs.obs_hotkey_unregister(hotkey_id)
				log_info(string.format("Unregistered hotkey for removed game: %s.%s", game_key, action_name))
			end
			hotkey_ids[game_key] = nil
		else
			-- Game still exists, check individual actions
			local valid_actions = {}
			for _, action_name in ipairs(game_config.actions or {}) do
				valid_actions[action_name] = true
			end
			
			-- Add system actions to valid list for the first game
			if game_key == next(GAMES) then
				valid_actions["undo"] = true
				valid_actions["clear"] = true
				valid_actions["start"] = true
			end
			
			-- Remove hotkeys for actions that no longer exist
			for action_name, hotkey_id in pairs(actions_map) do
				if not valid_actions[action_name] then
					log_info(string.format("Removing hotkey for removed action: %s.%s", game_key, action_name))
					obs.obs_hotkey_unregister(hotkey_id)
					hotkey_ids[game_key][action_name] = nil
				end
			end
		end
	end
end

local function refresh_config()
	log_info("🔄 Refreshing configuration from server...")
	init_games_from_server()

	log_info(string.format("Loaded %d games from server", table_length(GAMES)))
	for game_key, game_config in pairs(GAMES) do
		log_info(
			string.format(
				"  %s: %d actions",
				game_key,
				#(game_config.actions or {})
			)
		)
	end

	-- Clean up hotkeys for removed games/actions
	cleanup_removed_hotkeys()
	
	-- Register new hotkeys (existing ones are preserved)
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