// ContentView.swift
// Simple UI to install / uninstall the DriverKit extension.

import SwiftUI
import SystemExtensions
import Combine
import os.log

private let log = OSLog(subsystem: "com.xeneon.touch.app", category: "ui")

// Bundle ID of the dext — must match PRODUCT_BUNDLE_IDENTIFIER in the
// extension target's build settings.
private let kDriverBundleID = "com.jonathanmartin.XeneonTouchDriverApp.XeneonTouchDriver"

class DriverManager: NSObject, ObservableObject, OSSystemExtensionRequestDelegate {

    @Published var statusMessage = "Ready"
    @Published var isInstalled   = false

    func install() {
        statusMessage = "Installing driver…"
        let request = OSSystemExtensionRequest
            .activationRequest(forExtensionWithIdentifier: kDriverBundleID,
                               queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    func uninstall() {
        statusMessage = "Uninstalling driver…"
        let request = OSSystemExtensionRequest
            .deactivationRequest(forExtensionWithIdentifier: kDriverBundleID,
                                 queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    // MARK: – OSSystemExtensionRequestDelegate

    func request(_ request: OSSystemExtensionRequest,
                 didFinishWithResult result: OSSystemExtensionRequest.Result) {
        switch result {
        case .completed:
            isInstalled = (request is OSSystemExtensionRequest)
            statusMessage = "Driver installed ✓  —  reconnect the Xeneon Edge."
            os_log(.info, log: log, "Extension request completed")
        case .willCompleteAfterReboot:
            statusMessage = "Reboot required to complete installation."
        @unknown default:
            statusMessage = "Unknown result"
        }
    }

    func request(_ request: OSSystemExtensionRequest,
                 didFailWithError error: Error) {
        statusMessage = "Error: \(error.localizedDescription)"
        os_log(.error, log: log, "Extension request failed: %{public}@",
               error.localizedDescription)
    }

    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        statusMessage = "Approval required — check System Settings → Privacy & Security."
    }

    func request(_ request: OSSystemExtensionRequest,
                 actionForReplacingExtension existing: OSSystemExtensionProperties,
                 withExtension ext: OSSystemExtensionProperties)
        -> OSSystemExtensionRequest.ReplacementAction {
        return .replace
    }
}

struct ContentView: View {

    @StateObject private var driver = DriverManager()

    var body: some View {
        VStack(spacing: 20) {

            Image(systemName: "hand.point.up.fill")
                .font(.system(size: 48))
                .foregroundColor(.accentColor)

            Text("Xeneon Edge Touch Driver")
                .font(.title2.bold())

            Text("Enables 5-point multitouch for the Corsair Xeneon Edge on macOS.")
                .font(.callout)
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .frame(maxWidth: 320)

            Divider()

            Text(driver.statusMessage)
                .font(.footnote)
                .foregroundColor(.secondary)

            HStack(spacing: 12) {
                Button("Install Driver") {
                    driver.install()
                }
                .buttonStyle(.borderedProminent)

                Button("Uninstall") {
                    driver.uninstall()
                }
                .buttonStyle(.bordered)
            }

            Text("Requires: SIP disabled (dev) or Apple Developer signing (release)")
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .padding(32)
        .frame(minWidth: 400)
    }
}
