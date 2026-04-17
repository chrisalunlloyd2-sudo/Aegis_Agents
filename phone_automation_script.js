/**
 * 🧠 AEGIS-DIMON: Android Red Dot Automator
 * For Auto.js (Open Source v4.1.1) or MacroDroid JS.
 * 
 * Purpose: Scan screen for signals and trigger Desktop Red Dot.
 */

// --- CONFIG ---
// Replace with your Desktop's Local IP address
const DESKTOP_BRIDGE_URL = "http://192.168.x.x:5001/signal"; 

// 1. Request Screen Capture Permission
if (!requestScreenCapture()) {
    toast("Capture permission denied. Aegis-Mobile offline.");
    exit();
}

toast("Aegis Mobile Manifold: ACTIVE");

// 2. Main Scan Loop
while (true) {
    let img = captureScreen();
    
    // Scan for a specific color (Red #FF0000) in a region
    // Adjust region [x, y, width, height] based on what you want to detect
    let point = findColor(img, "#FF0000", {
        region: [0, 0, 1080, 500], 
        threshold: 4
    });

    if (point) {
        console.log("🔴 [DIMON] Signal detected at: " + point.x + ", " + point.y);
        
        // Trigger the Desktop Bridge
        try {
            http.post(DESKTOP_BRIDGE_URL, {
                "signal": "red_dot_detected",
                "x": point.x,
                "y": point.y
            });
            toast("Red Dot Synced to Desktop");
            sleep(5000); // Prevent spamming
        } catch (e) {
            console.log("❌ Connection Error: " + e);
        }
    }
    
    sleep(1000); // Check every 1 second
}
