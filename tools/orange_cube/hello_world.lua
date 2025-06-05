-- Hello World Lua Script for Orange Cube
-- ESP32 DroneBridge Upload Test

function update()
    gcs:send_text(0, "Hello from ESP32 DroneBridge Lua Upload!")
    return update, 5000  -- Run every 5 seconds
end

return update()