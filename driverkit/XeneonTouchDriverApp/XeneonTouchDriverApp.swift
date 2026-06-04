// XeneonTouchDriverApp.swift
// Minimal wrapper app required by macOS — DriverKit extensions must
// be embedded inside an app bundle. This app activates/deactivates
// the driver and shows status.

import SwiftUI
import SystemExtensions

@main
struct XeneonTouchDriverApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowResizability(.contentSize)
    }
}
