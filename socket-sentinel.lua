-- socket-sentinel.lua
-- OBS Lua script: send hotkey events over TCP (via netcat) to an external script.
-- Fetch YAML config from http://HOST:HTTP_PORT/config
-- Per-game hotkeys and scene-based gating.

local obs = obslua

----------------------------------------------------
-- CONFIG DEFAULTS
----------------------------------------------------

local HOST = "127.0.0.1" -- both TCP + HTTP hostname
local PORT = 5678 -- TCP port for action messages
local HTTP_PORT = 8088 -- NEW: port for fetching YAML via /config
local SS_TOKEN = "" -- Security token for authentication (configured in OBS settings)

local GAMES = {} -- populated from YAML
local hotkey_ids = {} -- [game][action] = id

----------------------------------------------------
-- LOGGING HELPERS
----------------------------------------------------

local function log_info(msg)
	obs.script_log(obs.LOG_INFO, "[socket-sentinel] " .. msg)
end

local function log_warn(msg)
	obs.script_log(obs.LOG_WARNING, "[socket-sentinel] " .. msg)
end

local function log_error(msg)
	obs.script_log(obs.LOG_ERROR, "[socket-sentinel] " .. msg)
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
-- TCP SEND VIA NETCAT
----------------------------------------------------
local function send_tcp_message(game_key, action_name)
	if not action_name or action_name == "" then
		return
	end

	-- Include token in TCP payload for authentication
	local payload = ""
	if SS_TOKEN and SS_TOKEN ~= "" then
		payload = payload .. "token=" .. SS_TOKEN .. "\n"
	end
	payload = payload .. "game=" .. tostring(game_key) .. "\n" .. "action=" .. action_name .. "\n"

	local cmd = string.format("printf %s | nc %s %d >/dev/null 2>&1 &", shell_escape(payload), HOST, PORT)

	log_info("Executing: " .. cmd)
	os.execute(cmd)
	log_info(
		string.format("Sent TCP message: game=%s action=%s → %s:%d", tostring(game_key), action_name, HOST, PORT)
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

		-- send both game and action to Python
		send_tcp_message(game_key, action_name)
	end
end

----------------------------------------------------
-- FETCH YAML FROM PYTHON /config
----------------------------------------------------

local function http_get(host, port, path, token)
	local auth_header = ""
	if token and token ~= "" then
		auth_header = string.format(' -H "Authorization: Bearer %s"', token)
	end
	local cmd = string.format("curl -fsSL%s http://%s:%d%s", auth_header, host, port, path)
	local f = io.popen(cmd, "r")
	if not f then
		return nil
	end
	local data = f:read("*a")
	f:close()
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
-- MINIMAL YAML PARSER FOR games.*.actions
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
			end
			goto continue
		end

		if not current_game then
			goto continue
		end

		if lvl == 4 and t == "actions:" then
			in_actions = true
			goto continue
		end

		if in_actions and lvl >= 6 then
			local akey = t:match("^([%w_]+)%s*:")
			if akey then
				table.insert(games[current_game].actions, akey)
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
-- REGISTER HOTKEYS
----------------------------------------------------

local function register_hotkeys()
	-- Register game-specific actions
	for game_key, g in pairs(GAMES) do
		hotkey_ids[game_key] = hotkey_ids[game_key] or {}
		for _, action_name in ipairs(g.actions or {}) do
			local internal_id = "socket_sentinel_" .. game_key .. "_" .. action_name
			local label = string.format("Socket Sentinel [%s]: %s", game_key, action_name)

			local id = obs.obs_hotkey_register_frontend(internal_id, label, make_hotkey_callback(game_key, action_name))

			if id then
				hotkey_ids[game_key][action_name] = id
				log_info("Registered hotkey: " .. label)
			else
				log_warn("Failed hotkey register: " .. internal_id)
			end
		end
	end
	
	-- Register system actions for the first game (they work globally)
	local first_game = next(GAMES)
	if first_game then
		local system_actions = {"undo", "clear", "start"}
		for _, action_name in ipairs(system_actions) do
			local internal_id = "socket_sentinel_system_" .. action_name
			local label = string.format("Socket Sentinel [SYSTEM]: %s", action_name)

			local id = obs.obs_hotkey_register_frontend(internal_id, label, make_hotkey_callback(first_game, action_name))

			if id then
				hotkey_ids[first_game] = hotkey_ids[first_game] or {}
				hotkey_ids[first_game][action_name] = id
				log_info("Registered system hotkey: " .. label)
			else
				log_warn("Failed system hotkey register: " .. internal_id)
			end
		end
	end
end

----------------------------------------------------
-- OBS API
----------------------------------------------------

function script_description()
	return [[
Socket Sentinel — Unified Hotkey Dispatcher

Enhancements:
  • Loads YAML config from Python @ /config
  • Per-game hotkeys (games.*.actions)
  • Hotkeys only fire when active scene matches the game key
  • Independent HTTP port for config fetch
]]
end

function script_properties()
	local props = obs.obs_properties_create()

	obs.obs_properties_add_text(props, "host", "Server Host", obs.OBS_TEXT_DEFAULT)
	obs.obs_properties_add_int(props, "port", "TCP Port (actions)", 1, 65535, 1)
	obs.obs_properties_add_int(props, "http_port", "HTTP Port (YAML /config)", 1, 65535, 1)
	obs.obs_properties_add_text(props, "ss_token", "Security Token (SS_TOKEN)", obs.OBS_TEXT_PASSWORD)

	return props
end

function script_defaults(settings)
	obs.obs_data_set_default_string(settings, "host", HOST)
	obs.obs_data_set_default_int(settings, "port", PORT)
	obs.obs_data_set_default_int(settings, "http_port", HTTP_PORT)
	obs.obs_data_set_default_string(settings, "ss_token", SS_TOKEN)
end

function script_update(settings)
	HOST = obs.obs_data_get_string(settings, "host") or "127.0.0.1"

	PORT = obs.obs_data_get_int(settings, "port")
	if PORT < 1 then
		PORT = 5678
	end

	HTTP_PORT = obs.obs_data_get_int(settings, "http_port")
	if HTTP_PORT < 1 then
		HTTP_PORT = 8088
	end

	SS_TOKEN = obs.obs_data_get_string(settings, "ss_token") or ""

	log_info(string.format("Updated settings → TCP=%s:%d HTTP=%s:%d Token=%s", HOST, PORT, HOST, HTTP_PORT, 
		SS_TOKEN ~= "" and "***SET***" or "NOT_SET"))
end

function script_load(settings)
	script_update(settings)

	init_games_from_server()
	if next(GAMES) == nil then
		log_error("No games loaded; aborting hotkey registration.")
		return
	end

	register_hotkeys()

	-- restore hotkey bindings
	for game_key, actions in pairs(hotkey_ids) do
		for action_name, id in pairs(actions) do
			local system_actions = {undo = true, clear = true, start = true}
			local internal_id
			if system_actions[action_name] then
				internal_id = "socket_sentinel_system_" .. action_name
			else
				internal_id = "socket_sentinel_" .. game_key .. "_" .. action_name
			end
			
			local a = obs.obs_data_get_array(settings, internal_id)
			if a then
				obs.obs_hotkey_load(id, a)
				obs.obs_data_array_release(a)
			end
		end
	end

	log_info("script_load complete.")
end

function script_save(settings)
	for game_key, actions in pairs(hotkey_ids) do
		for action_name, id in pairs(actions) do
			local system_actions = {undo = true, clear = true, start = true}
			local internal_id
			if system_actions[action_name] then
				internal_id = "socket_sentinel_system_" .. action_name
			else
				internal_id = "socket_sentinel_" .. game_key .. "_" .. action_name
			end
			
			local a = obs.obs_hotkey_save(id)
			obs.obs_data_set_array(settings, internal_id, a)
			obs.obs_data_array_release(a)
		end
	end
end

function script_unload()
	log_info("socket-sentinel unloaded.")
end
