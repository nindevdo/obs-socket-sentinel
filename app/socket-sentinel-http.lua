-- socket-sentinel-http.lua  
-- OBS Lua script: send hotkey events over HTTP POST (secure replacement for TCP)
-- Fetch YAML config from http://HOST:HTTP_PORT/config
-- Per-game hotkeys with auto-detection and manual selection.

local obs = obslua

----------------------------------------------------
-- CONFIG DEFAULTS
----------------------------------------------------

local HOST = "127.0.0.1" -- HTTP hostname
local HTTP_PORT = 8088 -- HTTP port for both actions and config
local SS_TOKEN = "" -- Security token for authentication

local GAMES = {} -- populated from YAML
local hotkey_ids = {} -- [game][action] = id

-- Game detection and selection
local AUTO_DETECT_GAME = true -- whether to auto-detect based on window title
local MANUAL_GAME_SELECTION = "" -- manually selected game key
local DETECTED_GAME = "" -- auto-detected game from window title
local CURRENT_WINDOW_TITLE = "" -- last detected window title for display

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
-- GAME DETECTION
----------------------------------------------------

-- Game detection patterns - maps window titles to game keys
local GAME_DETECTION_PATTERNS = {
	["hunt"] = "hunt_showdown",
	["hunt: showdown"] = "hunt_showdown",
	["enshrouded"] = "enshrouded",
	["chivalry"] = "chivalry2",
	["chivalry 2"] = "chivalry2",
	["fortnite"] = "fortnite",
	["helldivers"] = "hell_divers_2",
	["hell divers"] = "hell_divers_2"
}

local function get_active_window_title()
	-- Use xdotool to get active window title on Linux
	local cmd = "xdotool getwindowfocus getwindowname 2>/dev/null"
	local f = io.popen(cmd, "r")
	if not f then
		return nil
	end
	local title = f:read("*a")
	f:close()
	if title then
		return trim(title)
	end
	return nil
end

local function detect_game_from_window()
	local title = get_active_window_title()
	CURRENT_WINDOW_TITLE = title or "No window detected"
	
	if not title or title == "" then
		return nil
	end
	
	local title_lower = title:lower()
	log_info("Checking window title: " .. title)
	
	for pattern, game_key in pairs(GAME_DETECTION_PATTERNS) do
		if title_lower:find(pattern, 1, true) then -- plain text search
			log_info("✓ Detected game: " .. game_key .. " from window title: " .. title)
			return game_key
		end
	end
	
	log_info("✗ No game pattern matched for window: " .. title)
	return nil
end

local function get_current_game_key()
	-- Priority: Manual selection > Auto-detection > First available game
	if MANUAL_GAME_SELECTION ~= "" and GAMES[MANUAL_GAME_SELECTION] then
		return MANUAL_GAME_SELECTION
	end
	
	if AUTO_DETECT_GAME then
		local detected = detect_game_from_window()
		if detected and GAMES[detected] then
			DETECTED_GAME = detected
			return detected
		end
	end
	
	-- Fallback to first available game
	local first_game = next(GAMES)
	return first_game
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
	
	local url
	if (HOST:find("^http://") or HOST:find("^https://")) then
		url = HOST .. "/action"
	else
		url = "http://" .. HOST .. ":" .. HTTP_PORT .. "/action"
	end
	
	local cmd = string.format(
		"curl -s -X POST %s -H 'Content-Type: application/json' %s -d %s >/dev/null 2>&1 &",
		url, auth_header, shell_escape(json_payload)
	)

	log_info("Executing: " .. cmd)
	os.execute(cmd)
	log_info(
		string.format("Sent HTTP action: game=%s action=%s → %s:%d/action", tostring(game_key), action_name, HOST, HTTP_PORT)
	)
end

----------------------------------------------------
-- HELPER FUNCTIONS
----------------------------------------------------
-- Helper function to extract readable hotkey string from OBS hotkey data
local function extract_hotkey_string(hotkey_id)
	-- Use OBS scripting API to get the actual hotkey combination
	if not hotkey_id then
		return "Not Set"
	end
	
	-- Try to get key combination from hotkey save data
	local hotkey_save_array = obs.obs_hotkey_save(hotkey_id)
	if hotkey_save_array then
		local count = obs.obs_data_array_count(hotkey_save_array)
		if count > 0 then
			local binding_data = obs.obs_data_array_item(hotkey_save_array, 0)
			local binding_data = obs.obs_data_array_item(hotkey_save_array, 0)
			if binding_data then
				local key = obs.obs_data_get_string(binding_data, "key")
				local modifiers = obs.obs_data_get_obj(binding_data, "modifiers")
				
				local key_str = ""
				if modifiers then
					local shift = obs.obs_data_get_bool(modifiers, "shift")
					local ctrl = obs.obs_data_get_bool(modifiers, "control") 
					local alt = obs.obs_data_get_bool(modifiers, "alt")
					local cmd = obs.obs_data_get_bool(modifiers, "command")
					
					if ctrl then key_str = key_str .. "Ctrl+" end
					if alt then key_str = key_str .. "Alt+" end
					if shift then key_str = key_str .. "Shift+" end
					if cmd then key_str = key_str .. "Cmd+" end
					
					obs.obs_data_release(modifiers)
				end
				
				key_str = key_str .. (key or "")
				obs.obs_data_release(binding_data)
				obs.obs_data_array_release(hotkey_save_array)
				
				return key_str ~= "" and key_str or "Not Set"
			end
		end
		obs.obs_data_array_release(hotkey_save_array)
	end
	
	return "Not Set"
end

----------------------------------------------------
-- HOTKEY MAPPINGS SYNC VIA CURL
----------------------------------------------------
local function send_hotkey_mappings()
	log_info("🔑 Syncing hotkey mappings to server...")
	
	-- Build hotkey mappings from all registered hotkeys
	local mappings = {}
	
	for game_key, actions_map in pairs(hotkey_ids) do
		for action_name, hotkey_id in pairs(actions_map) do
			-- Get a simplified hotkey representation
			local hotkey_str = extract_hotkey_string(hotkey_id)
			if hotkey_str and hotkey_str ~= "" then
				mappings[action_name] = hotkey_str
				log_info(string.format("  %s: %s", action_name, hotkey_str))
			end
		end
	end
	
	if next(mappings) == nil then
		log_info("📭 No hotkey mappings to send")
		return
	end
	
	-- Create JSON payload
	local mappings_json = "{"
	local first = true
	for action, hotkey in pairs(mappings) do
		if not first then
			mappings_json = mappings_json .. ","
		end
		mappings_json = mappings_json .. string.format('"%s":"%s"', action, hotkey)
		first = false
	end
	mappings_json = mappings_json .. "}"
	
	local json_payload = string.format('{"mappings":%s}', mappings_json)
	
	-- Prepare curl command with proper authentication
	local auth_header = ""
	if SS_TOKEN and SS_TOKEN ~= "" then
		auth_header = string.format("-H 'Authorization: Bearer %s'", SS_TOKEN)
	end
	
	local cmd = string.format(
		"curl -s -X POST http://%s:%d/hotkeys -H 'Content-Type: application/json' %s -d %s >/dev/null 2>&1 &",
		HOST, HTTP_PORT, auth_header, shell_escape(json_payload)
	)

	log_info("Executing: " .. cmd)
	os.execute(cmd)
	log_info(string.format("📤 Sent %d hotkey mappings to server", table_length(mappings)))
end

----------------------------------------------------
-- HOTKEY CALLBACK
----------------------------------------------------
local function make_hotkey_callback(hotkey_game_key, action_name)
	return function(pressed)
		if not pressed then
			return
		end

		-- Get the current active game
		local current_game = get_current_game_key()
		if not current_game then
			log_warn("No game detected or configured - ignoring hotkey")
			return
		end

		-- System actions (undo, clear, start) work globally regardless of game
		local system_actions = {undo = true, clear = true, start = true}
		
		if not system_actions[action_name] then
			-- Game gating: only fire when this hotkey's game matches the current active game
			if normalize_name(current_game) ~= normalize_name(hotkey_game_key) then
				log_info(
					string.format(
						"Ignoring [%s:%s] because current game '%s' != hotkey game '%s'",
						hotkey_game_key,
						action_name,
						current_game,
						hotkey_game_key
					)
				)
				return
			end
		end

		local detection_method = "manual"
		if AUTO_DETECT_GAME and current_game == DETECTED_GAME then
			detection_method = "auto-detected"
		elseif MANUAL_GAME_SELECTION ~= "" then
			detection_method = "manual selection"
		else
			detection_method = "fallback"
		end

		log_info(
			string.format("Hotkey triggered → game=%s action=%s (%s)", current_game, action_name, detection_method)
		)

		-- send current game and action via HTTP
		send_http_action(current_game, action_name)
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
	
	local url
	if (host:find("^http://") or host:find("^https://")) then
		url = host .. path
	else
		url = "http://" .. host .. ":" .. port .. path
	end

	local cmd = string.format(
		"curl -s %s %s",
		url, auth_header
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
	local url
	if (HOST:find("^http://") or HOST:find("^https://")) then
		url = HOST .. "/config"
	else
		url = "http://" .. HOST .. ":" .. HTTP_PORT .. "/config"
	end
	log_info(string.format("Fetching YAML from %s ...", url))
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
	-- Only register hotkeys that don't already exist in our tracking table
	-- This prevents duplicates when refresh config is clicked
	
	-- Register game-specific actions
	for game_key, g in pairs(GAMES) do
		hotkey_ids[game_key] = hotkey_ids[game_key] or {}
		for _, action_name in ipairs(g.actions or {}) do
			-- Skip if hotkey already exists in our tracking table
			if hotkey_ids[game_key][action_name] then
				-- log_info(string.format("Skipping existing hotkey: %s.%s", game_key, action_name))
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
			-- Skip if system hotkey already exists in our tracking table
			if hotkey_ids[first_game][action_name] then
				-- log_info(string.format("Skipping existing system hotkey: %s", action_name))
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
	
	-- Send hotkey mappings to server after registration
	log_info("🔄 Sending updated hotkey mappings to server...")
	-- Use a small delay to ensure hotkeys are fully registered
	obs.timer_add(function()
		send_hotkey_mappings()
		obs.remove_current_callback()
	end, 1000)
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

	-- Only clean up on manual refresh (not on script startup)
	-- This preserves hotkeys across OBS restarts
	cleanup_removed_hotkeys()
	
	-- Register hotkeys (OBS handles duplicates automatically)
	register_hotkeys()
	log_info("✅ Configuration refresh complete")
end

local function initial_load_config()
	log_info("🔄 Loading initial configuration from server...")
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

	-- Don't cleanup on initial load - preserve existing hotkeys
	register_hotkeys()
	log_info("✅ Initial configuration loaded")
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
<li>🎯 Game-based action gating with auto-detection</li>
<li>🔄 Dynamic config loading</li>
</ul>
<p><strong>Setup:</strong></p>
<ol>
<li>Enter your server host/port and authentication token</li>
<li>Configure game detection or manual selection</li>
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
	
	-- Game detection options
	obs.obs_properties_add_bool(props, "auto_detect", "Auto-detect game from window title")
	
	local game_list = obs.obs_properties_add_list(props, "manual_game", "Manual game selection", obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
	obs.obs_property_list_add_string(game_list, "Auto-detect / First Available", "")
	
	-- Populate with games from config
	for game_key, _ in pairs(GAMES) do
		obs.obs_property_list_add_string(game_list, game_key, game_key)
	end
	
	-- Status display (read-only text fields)
	obs.obs_properties_add_text(props, "status_window", "Current Window Title", obs.OBS_TEXT_INFO)
	obs.obs_properties_add_text(props, "status_detected", "Detected Game", obs.OBS_TEXT_INFO) 
	obs.obs_properties_add_text(props, "status_active", "Active Game", obs.OBS_TEXT_INFO)
	
	obs.obs_properties_add_button(props, "test_detection", "🔍 Test Detection Now", function()
		test_game_detection()
		return true
	end)
	
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
	obs.obs_data_set_default_bool(settings, "auto_detect", AUTO_DETECT_GAME)
	obs.obs_data_set_default_string(settings, "manual_game", MANUAL_GAME_SELECTION)
end

function script_update(settings)
	HOST = obs.obs_data_get_string(settings, "host") or "127.0.0.1"

	HTTP_PORT = obs.obs_data_get_int(settings, "http_port")
	if HTTP_PORT < 1 then
		HTTP_PORT = 8088
	end

	SS_TOKEN = obs.obs_data_get_string(settings, "ss_token") or ""
	AUTO_DETECT_GAME = obs.obs_data_get_bool(settings, "auto_detect")
	MANUAL_GAME_SELECTION = obs.obs_data_get_string(settings, "manual_game") or ""

	local detection_info = ""
	if MANUAL_GAME_SELECTION ~= "" then
		detection_info = "Manual: " .. MANUAL_GAME_SELECTION
	elseif AUTO_DETECT_GAME then
		detection_info = "Auto-detect enabled"
	else
		detection_info = "Fallback to first game"
	end

	-- Update status fields
	update_status_display(settings)

	log_info(string.format("Updated settings → HTTP=%s:%d Token=%s Game=%s", HOST, HTTP_PORT, 
		SS_TOKEN ~= "" and "***SET***" or "NOT_SET", detection_info))
end

-- Function to test game detection and update status display
function test_game_detection()
	local detected = detect_game_from_window()
	DETECTED_GAME = detected or ""
	local active_game = get_current_game_key()
	
	log_info("=== GAME DETECTION TEST ===")
	log_info("Window Title: " .. (CURRENT_WINDOW_TITLE or "None"))
	log_info("Detected Game: " .. (DETECTED_GAME ~= "" and DETECTED_GAME or "None"))
	log_info("Active Game: " .. (active_game or "None"))
	log_info("Auto-detect: " .. (AUTO_DETECT_GAME and "Enabled" or "Disabled"))
	log_info("Manual selection: " .. (MANUAL_GAME_SELECTION ~= "" and MANUAL_GAME_SELECTION or "None"))
	log_info("==========================")
end

-- Function to update status display in properties
function update_status_display(settings)
	if not settings then
		return
	end
	
	-- Force a detection check
	local detected = detect_game_from_window()
	DETECTED_GAME = detected or ""
	local active_game = get_current_game_key()
	
	-- Update the status fields
	obs.obs_data_set_string(settings, "status_window", CURRENT_WINDOW_TITLE or "No window detected")
	obs.obs_data_set_string(settings, "status_detected", DETECTED_GAME ~= "" and DETECTED_GAME or "No game detected")
	obs.obs_data_set_string(settings, "status_active", active_game or "No game active")
end

function script_load(settings)
	script_update(settings)
	
	log_info("🚀 Socket Sentinel HTTP Client loaded")
	log_info("📡 Using secure HTTP POST instead of insecure TCP")
	log_info("🔒 Authentication: " .. (SS_TOKEN ~= "" and "Enabled" or "⚠️  DISABLED"))
	
	-- Use initial load on startup (preserves existing hotkeys)
	initial_load_config()
	
	-- Restore hotkey bindings from saved settings (THIS IS THE KEY!)
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
	
	log_info("✅ Script load complete with preserved hotkey bindings")
	
	-- Start periodic hotkey mapping sync (every 30 seconds)
	obs.timer_add(send_hotkey_mappings, 30000)
	
	-- Send initial hotkey mappings after a short delay
	obs.timer_add(function()
		send_hotkey_mappings()
		obs.remove_current_callback()
	end, 3000)
end

function script_save(settings)
	-- Save hotkey bindings so they persist across OBS restarts
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
	-- Remove timer
	obs.timer_remove(send_hotkey_mappings)
	clear_hotkeys()
	log_info("Socket Sentinel HTTP Client unloaded")
end