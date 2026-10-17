import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "local.redragon-battery"
  ipcTarget: "local.redragon-battery"

  readonly property string scriptPath: {
    var localUrl = Qt.resolvedUrl("redragon_battery.py").toString()
    if (localUrl.indexOf("file://") === 0) return localUrl.substring(7)
    return Quickshell.env("HOME") + "/.config/omarchy/plugins/local.redragon-battery/redragon_battery.py"
  }

  property bool deviceConnected: false
  property bool batteryValid: false
  property string connectionType: ""
  property int percentage: 0
  property int voltageMv: 0
  property bool isCharging: false
  property string lastError: ""
  property var lastValidDate: null
  property int ticker: 0

  // High-contrast, theme-integrated text and surface tokens for the popup
  readonly property color popupTextColor: Color.popups.text
  readonly property color popupBgColor: Color.background
  readonly property color popupBorderColor: Color.popups.border
  readonly property color popupMutedColor: Color.muted

  // Permanent red only when battery is critical (<= 5%) and discharging
  readonly property bool isCritical: batteryValid && !isCharging && percentage <= 5

  readonly property string statusText: {
    if (!deviceConnected) return "DISCONNECTED"
    if (!batteryValid) return "UNKNOWN"
    return isCharging ? "CHARGING" : "DISCHARGING"
  }

  readonly property string lastUpdateText: {
    var _ = root.ticker
    if (!root.lastValidDate) return "Never"
    var now = new Date()
    var diffSec = Math.floor((now.getTime() - root.lastValidDate.getTime()) / 1000)
    if (diffSec < 10) return "Just now"
    if (diffSec < 60) return diffSec + "s ago"
    if (diffSec < 3600) return Math.floor(diffSec / 60) + "m ago"
    return Math.floor(diffSec / 3600) + "h ago"
  }

  readonly property string tooltip: {
    if (!deviceConnected) {
      return "Redragon M916 Pro 1K\nStatus: Disconnected"
    }
    if (!batteryValid) {
      return "Redragon M916 Pro 1K\n" +
             "Battery: --%\n" +
             "Voltage: --\n" +
             "Status:  Unknown" +
             (lastError ? " (" + lastError + ")" : "")
    }
    var statusStr = isCharging ? "Charging" : "Discharging"
    var vStr = voltageMv > 0 ? (voltageMv / 1000.0).toFixed(2) + " V" : "--"
    var modeStr = connectionType === "usb" ? " (USB)" : " (2.4GHz)"
    return "Redragon M916 Pro 1K" + modeStr + "\n" +
           "Battery: " + percentage + "%\n" +
           "Voltage: " + vStr + "\n" +
           "Status:  " + statusStr
  }

  function handleProcessOutput(rawText) {
    if (!rawText || rawText.trim() === "") return
    try {
      var data = JSON.parse(rawText.trim())
      root.deviceConnected = data.connected === true
      root.batteryValid = data.valid === true
      root.connectionType = data.connection || ""
      root.lastError = data.error || ""
      if (data.valid) {
        root.percentage = (data.percentage !== null && data.percentage !== undefined) ? data.percentage : 0
        root.voltageMv = (data.voltage_mv !== null && data.voltage_mv !== undefined) ? data.voltage_mv : 0
        root.isCharging = data.is_charging === true
        root.lastValidDate = new Date()
        root.ticker++
      } else {
        // Prevent carrying stale readings into current state
        root.percentage = 0
        root.voltageMv = 0
        root.isCharging = false
      }
    } catch (e) {
      console.warn("[local.redragon-battery] Error parsing response:", e, rawText)
    }
  }

  function refresh() {
    if (!batteryProc.running) {
      batteryProc.running = true
    }
  }

  visible: deviceConnected
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: batteryProc
    command: ["python3", root.scriptPath]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleProcessOutput(text)
    }
  }

  // Periodic hardware poll every 60 seconds
  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  // Live timer to refresh elapsed 'last update' label while panel is open
  Timer {
    interval: 5000
    running: root.opened
    repeat: true
    onTriggered: root.ticker++
  }

  onOpenedChanged: {
    if (opened && (!batteryValid || !lastValidDate)) {
      refresh()
    }
  }

  // Small indicator button on the Omarchy status bar
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: (root.batteryValid && root.isCharging) ? ("󰍽 󱐋 " + root.percentage + "%")
                                                 : ("󰍽 " + (root.batteryValid ? (root.percentage + "%") : "--%"))
    fontSize: Style.font.caption
    horizontalMargin: 6
    active: root.isCritical
    tooltipText: root.opened ? "" : root.tooltip
    onPressed: function() { root.toggle() }
  }

  // Floating popup panel
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened && root.deviceConnected
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTextKey: function(t) { if (t === "r" || t === "R") root.refresh() }

      // Explicit solid dark theme background to guarantee high contrast against any wallpaper
      Rectangle {
        id: panelBg
        anchors.fill: parent
        z: -1
        color: root.popupBgColor
        radius: Style.cornerRadius
        opacity: 0.98
      }

      Column {
        id: column
        z: 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(14)

        // ---------- Hero: Big Mouse Icon · Title / Status · Big Percentage ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight, heroPercent.implicitHeight)

          Text {
            id: heroIcon
            textFormat: Text.PlainText
            text: (root.batteryValid && root.isCharging) ? "󰍽 󱐋" : "󰍽"
            color: root.isCritical ? Color.urgent : ((root.batteryValid && root.isCharging) ? Color.accent : root.popupTextColor)
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.display
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(12)
            anchors.right: heroPercent.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Redragon M916 Pro 1K"
              color: root.popupTextColor
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              id: heroStatus
              textFormat: Text.PlainText
              text: root.statusText
              color: (root.batteryValid && root.isCharging) ? Color.accent : root.popupMutedColor
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.1
              elide: Text.ElideRight
              width: parent.width
            }
          }

          Text {
            id: heroPercent
            textFormat: Text.PlainText
            text: root.batteryValid ? (root.percentage + "%") : "--%"
            color: root.isCritical ? Color.urgent : root.popupTextColor
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.displayLarge
            font.bold: true
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        // ---------- Battery Progress Bar ----------
        Item {
          width: parent.width
          implicitHeight: Style.space(8)

          Rectangle {
            id: barTrack
            anchors.fill: parent
            radius: height / 2
            color: Qt.rgba(root.popupTextColor.r, root.popupTextColor.g, root.popupTextColor.b, 0.16)
          }

          Rectangle {
            id: barFill
            anchors.left: barTrack.left
            anchors.verticalCenter: barTrack.verticalCenter
            height: barTrack.height
            radius: barTrack.radius
            color: root.isCritical ? Color.urgent : ((root.batteryValid && root.isCharging) ? Color.accent : root.popupTextColor)
            width: root.batteryValid ? Math.max(barTrack.height, barTrack.width * Math.min(1.0, Math.max(0.0, root.percentage / 100.0))) : 0
            visible: root.batteryValid && root.percentage > 0

            Behavior on width { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: 160 } }
          }
        }

        // ---------- Information Columns ----------
        Row {
          width: parent.width
          spacing: Style.space(20)

          // Left column
          Column {
            width: (parent.width - parent.spacing) / 2
            spacing: Style.space(6)

            InfoPair {
              label: "Voltage"
              value: (root.batteryValid && root.voltageMv > 0) ? (root.voltageMv / 1000.0).toFixed(2) + " V" : "--"
            }
            InfoPair {
              label: "Connection"
              value: root.connectionType === "usb" ? "USB" : (root.connectionType === "wireless" ? "2.4 GHz" : "--")
            }
          }

          // Right column
          Column {
            width: (parent.width - parent.spacing) / 2
            spacing: Style.space(6)

            InfoPair {
              label: "Last update"
              value: root.lastUpdateText
            }
            InfoPair {
              label: "Device"
              value: "M916 Pro 1K"
            }
          }
        }

        // ---------- Discrete Action Row ----------
        PanelSeparator {
          foreground: root.popupBorderColor
          opacity: 0.6
        }

        Row {
          width: parent.width

          Item {
            width: parent.width - refreshBtn.implicitWidth
            height: 1
          }

          Button {
            id: refreshBtn
            iconText: "\uf021"
            iconSize: Style.font.caption
            text: batteryProc.running ? "Updating..." : "Refresh"
            fontSize: Style.font.bodySmall
            foreground: root.popupTextColor
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            horizontalPadding: Style.space(10)
            verticalPadding: Style.space(4)
            bordered: true
            onClicked: root.refresh()
          }
        }
      }
    }
  }

  // Component definition for column key/value pairs
  component InfoPair: Row {
    property string label: ""
    property string value: ""

    width: parent.width
    spacing: Style.space(8)

    InfoLabel { text: label }
    Item {
      width: Math.max(0, parent.width - parent.children[0].implicitWidth - parent.children[2].implicitWidth - parent.spacing * 2)
      height: 1
    }
    InfoValue { text: value }
  }

  component InfoLabel: Text {
    textFormat: Text.PlainText
    color: root.popupMutedColor
    font.family: root.bar ? root.bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  component InfoValue: Text {
    textFormat: Text.PlainText
    color: root.popupTextColor
    font.family: root.bar ? root.bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.bodySmall
    font.bold: true
  }
}
