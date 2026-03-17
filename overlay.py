import sys
import objc
from AppKit import *
from PyObjCTools import AppHelper

def create_overlay(message):
    app = NSApplication.sharedApplication()
    # hide icon from dock
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    
    # Create the window
    rect = NSMakeRect(0, 0, 350, 50)
    window_mask = NSWindowStyleMaskBorderless
    
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, window_mask, NSBackingStoreBuffered, False
    )
    
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.2, 0.8))
    window.setHasShadow_(False)
    # Always on top
    window.setLevel_(NSFloatingWindowLevel)
    # Ignore mouse clicks
    window.setIgnoresMouseEvents_(True)
    
    # Calculate pos: Center horizontally, near bottom/middle
    screen_rect = NSScreen.mainScreen().frame()
    x = (screen_rect.size.width - 350) / 2
    # Place it near bottom? or near top? The user said "ホバーなどで" (hovering).
    # Let's put it at y = 100 (near bottom) or top
    y = 100
    window.setFrameOrigin_(NSMakePoint(x, y))
    
    # Create a wrapper view
    class RoundedView(NSView):
        def drawRect_(self, dirtyRect):
            NSColor.clearColor().set()
            NSRectFill(dirtyRect)
            
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 10.0, 10.0)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.2, 0.85).set()
            path.fill()
            
            # Draw border
            path.setLineWidth_(2.0)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.5, 0.8, 1.0).set()
            path.stroke()

    view = RoundedView.alloc().initWithFrame_(window.contentView().bounds())
    window.setContentView_(view)
    
    # Create a label (NSTextField)
    label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 5, 350, 40))
    label.setStringValue_(message)
    label.setTextColor_(NSColor.whiteColor())
    label.setFont_(NSFont.boldSystemFontOfSize_(18))
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(NSTextAlignmentCenter)
    
    view.addSubview_(label)
    
    window.makeKeyAndOrderFront_(None)
    
    # Run the event loop
    AppHelper.runEventLoop()

if __name__ == '__main__':
    msg = sys.argv[1] if len(sys.argv) > 1 else "🛑 停止: Cmd+Ctrl+X"
    create_overlay(msg)
