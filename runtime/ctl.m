/* Test control channel, enabled by X86RT_CTL=<dir>: lets a test drive the app without a
 * debugger or a visible screen.  Every 0.25 s a main run-loop timer (common modes, so it also
 * fires inside the app's modal loops, even ones started from a main-queue block) reads
 * <dir>/cmd (one command per line), deletes it, runs the commands and appends results to
 * <dir>/out.txt.
 *
 *   snap               render each visible window (front to back) to <dir>/win<i>.png
 *   views <i>          dump window i's view tree
 *   click <i> <x> <y>  left click at (x, y), points from window i's top-left corner
 *   drag <i> <x0> <y0> <x1> <y1>
 *   key <i> <text>     type text into window i
 *   menu <path>        perform a main-menu item, path like File/New
 *   windows            list every window, visible or not
 *   player             state of every AVPlayerView's player
 *   activate           act as if the app became active (a locked screen never activates it)
 *   visible            from now on report windows and app as visible and active, and post
 *                      the occlusion/activation notifications (testing with a locked screen)
 *   call <selector>    send selector (with nil argument) to the app delegate, window
 *                      delegates, window controllers and content view controllers that respond;
 *                      sent from a run-loop timer so a modal loop it starts keeps this channel alive
 *
 * Built with -DCTL_INJECT it is a dylib that starts itself, for comparing against the
 * original x86_64 app (DYLD_INSERT_LIBRARIES into a re-signed copy).
 */
#import <AppKit/AppKit.h>
#import <AVKit/AVKit.h>
#import <objc/runtime.h>

static NSString *g_dir;
static NSTimer *g_timer;

static void say(NSString *s)
{
    NSString *p = [g_dir stringByAppendingPathComponent:@"out.txt"];
    NSFileHandle *h = [NSFileHandle fileHandleForWritingAtPath:p];
    if (!h) {
        [[NSFileManager defaultManager] createFileAtPath:p contents:nil attributes:nil];
        h = [NSFileHandle fileHandleForWritingAtPath:p];
    }
    [h seekToEndOfFile];
    [h writeData:[[s stringByAppendingString:@"\n"] dataUsingEncoding:NSUTF8StringEncoding]];
    [h closeFile];
}

static NSArray<NSWindow *> *visible_windows(void)
{
    NSMutableArray *out = [NSMutableArray array];
    for (NSWindow *w in [NSApp orderedWindows])
        if ([w isVisible]) [out addObject:w];
    return out;
}

static void snap(void)
{
    int i = 0;
    for (NSWindow *w in visible_windows()) {
        NSView *v = [[w contentView] superview] ?: [w contentView];
        NSBitmapImageRep *r = [v bitmapImageRepForCachingDisplayInRect:[v bounds]];
        [v cacheDisplayInRect:[v bounds] toBitmapImageRep:r];
        NSString *p = [g_dir stringByAppendingPathComponent:[NSString stringWithFormat:@"win%d.png", i]];
        [[r representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:p atomically:YES];
        say([NSString stringWithFormat:@"win%d %@ %@ '%@' %@ key=%d", i, @([w windowNumber]), [w className], [w title],
                                       NSStringFromRect([w frame]), [w isKeyWindow]]);
        i++;
    }
    say(@"snap done");
}

static void dump_views(NSView *v, int depth, NSMutableString *o)
{
    [o appendFormat:@"%*s%@ %@%@\n", depth * 2, "", [v className], NSStringFromRect([v frame]), [v isHidden] ? @" hidden" : @""];
    for (NSView *s in [v subviews]) dump_views(s, depth + 1, o);
}

static NSWindow *window_at(NSArray *a, NSString *s)
{
    NSInteger i = [s integerValue];
    return i < (NSInteger)[a count] ? a[i] : nil;
}

static void mouse(NSWindow *w, NSEventType type, NSPoint top_left)
{
    NSPoint p = NSMakePoint(top_left.x, [w frame].size.height - top_left.y);
    NSEvent *e = [NSEvent mouseEventWithType:type location:p modifierFlags:0 timestamp:[[NSProcessInfo processInfo] systemUptime]
                                windowNumber:[w windowNumber] context:nil eventNumber:0 clickCount:1
                                    pressure:type == NSEventTypeLeftMouseUp ? 0 : 1];
    /* queued, not sent: a control's tracking loop pulls the rest of the gesture from the queue */
    [NSApp postEvent:e atStart:NO];
}

static NSMenuItem *menu_item(NSMenu *m, NSArray<NSString *> *path)
{
    for (NSMenuItem *it in [m itemArray]) {
        if (![[it title] isEqualToString:path[0]]) continue;
        if ([path count] == 1) return it;
        return [it submenu] ? menu_item([it submenu], [path subarrayWithRange:NSMakeRange(1, [path count] - 1)]) : nil;
    }
    return nil;
}

static void find_players(NSView *v, NSMutableArray *out)
{
    if ([v isKindOfClass:[AVPlayerView class]]) [out addObject:v];
    for (NSView *s in [v subviews]) find_players(s, out);
}

static double secs(CMTime t) { return t.timescale ? (double)t.value / t.timescale : NAN; }

static void players(void)
{
    for (NSWindow *w in visible_windows()) {
        NSMutableArray *a = [NSMutableArray array];
        find_players([w contentView], a);
        for (AVPlayerView *pv in a) {
            AVPlayer *p = [pv player];
            AVPlayerItem *it = [p currentItem];
            say([NSString stringWithFormat:@"player %@ rate=%g status=%ld item=%ld t=%g/%g err=%@ itemerr=%@ url=%@", pv,
                                           [p rate], (long)[p status], (long)[it status], secs([it currentTime]), secs([it duration]), [p error], [it error],
                                           [[it asset] isKindOfClass:[AVURLAsset class]] ? [(AVURLAsset *)[it asset] URL] : nil]);
        }
    }
    say(@"player done");
}

static NSUInteger visible_occlusion(id self, SEL _cmd) { return NSWindowOcclusionStateVisible; }
static BOOL yes(id self, SEL _cmd) { return YES; }

static void pretend_visible(void)
{
    method_setImplementation(class_getInstanceMethod([NSWindow class], @selector(occlusionState)), (IMP)visible_occlusion);
    method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(occlusionState)), (IMP)visible_occlusion);
    method_setImplementation(class_getInstanceMethod([NSApplication class], @selector(isActive)), (IMP)yes);
    NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
    [nc postNotificationName:NSApplicationDidChangeOcclusionStateNotification object:NSApp];
    [nc postNotificationName:NSApplicationDidBecomeActiveNotification object:NSApp];
    for (NSWindow *w in visible_windows()) {
        [nc postNotificationName:NSWindowDidChangeOcclusionStateNotification object:w];
        [nc postNotificationName:NSWindowDidBecomeKeyNotification object:w];
        [nc postNotificationName:NSWindowDidBecomeMainNotification object:w];
    }
    say(@"visible done");
}

static void run(NSString *line)
{
    NSArray *f = [line componentsSeparatedByString:@" "];
    NSString *c = f[0];
    NSArray *ws = visible_windows();
    if ([c isEqualToString:@"snap"]) {
        snap();
    } else if ([c isEqualToString:@"windows"]) {
        for (NSWindow *w in [NSApp windows])
            say([NSString stringWithFormat:@"%@ %@ '%@' %@ visible=%d alpha=%g level=%ld onscreen=%d", @([w windowNumber]), [w className], [w title],
                                           NSStringFromRect([w frame]), [w isVisible], [w alphaValue], (long)[w level], [w isOnActiveSpace]]);
        say(@"windows done");
    } else if ([c isEqualToString:@"player"]) {
        players();
    } else if ([c isEqualToString:@"visible"]) {
        pretend_visible();
    } else if ([c isEqualToString:@"call"] && [f count] > 1) {
        SEL sel = NSSelectorFromString(f[1]);
        NSMutableArray *targets = [NSMutableArray array];
        if ([NSApp delegate]) [targets addObject:[NSApp delegate]];
        for (NSWindow *w in ws) {
            for (id t in @[ (id)[w delegate] ?: [NSNull null], [w windowController] ?: [NSNull null], [w contentViewController] ?: [NSNull null] ])
                if (t != [NSNull null] && ![targets containsObject:t]) [targets addObject:t];
        }
        for (id t in targets)
            if ([t respondsToSelector:sel]) {
                [t performSelector:sel withObject:nil afterDelay:0 inModes:@[ NSRunLoopCommonModes ]];
                say([NSString stringWithFormat:@"calling %@ on %@", f[1], t]);
            }
        say(@"call done");
    } else if ([c isEqualToString:@"activate"]) {
        [NSApp activateIgnoringOtherApps:YES];
        [[ws firstObject] makeKeyAndOrderFront:nil];
        [[NSNotificationCenter defaultCenter] postNotificationName:NSApplicationDidBecomeActiveNotification object:NSApp];
        say([NSString stringWithFormat:@"activate active=%d key=%@", [NSApp isActive], [NSApp keyWindow]]);
    } else if ([c isEqualToString:@"views"] && [f count] > 1) {
        NSWindow *w = window_at(ws, f[1]);
        NSMutableString *o = [NSMutableString string];
        if (w) dump_views([[w contentView] superview] ?: [w contentView], 0, o);
        say(o);
    } else if ([c isEqualToString:@"click"] && [f count] > 3) {
        NSWindow *w = window_at(ws, f[1]);
        NSPoint p = NSMakePoint([f[2] doubleValue], [f[3] doubleValue]);
        mouse(w, NSEventTypeLeftMouseDown, p);
        mouse(w, NSEventTypeLeftMouseUp, p);
        say([NSString stringWithFormat:@"clicked %@", line]);
    } else if ([c isEqualToString:@"drag"] && [f count] > 5) {
        NSWindow *w = window_at(ws, f[1]);
        NSPoint a = NSMakePoint([f[2] doubleValue], [f[3] doubleValue]), b = NSMakePoint([f[4] doubleValue], [f[5] doubleValue]);
        mouse(w, NSEventTypeLeftMouseDown, a);
        for (int i = 1; i <= 10; i++)
            mouse(w, NSEventTypeLeftMouseDragged, NSMakePoint(a.x + (b.x - a.x) * i / 10, a.y + (b.y - a.y) * i / 10));
        mouse(w, NSEventTypeLeftMouseUp, b);
        say([NSString stringWithFormat:@"dragged %@", line]);
    } else if ([c isEqualToString:@"key"] && [f count] > 2) {
        NSWindow *w = window_at(ws, f[1]);
        NSString *t = [[f subarrayWithRange:NSMakeRange(2, [f count] - 2)] componentsJoinedByString:@" "];
        for (int k = 0; k < 2; k++) {
            NSEventType type = k ? NSEventTypeKeyUp : NSEventTypeKeyDown;
            NSEvent *e = [NSEvent keyEventWithType:type location:NSZeroPoint modifierFlags:0 timestamp:0
                                      windowNumber:[w windowNumber] context:nil characters:t charactersIgnoringModifiers:t
                                         isARepeat:NO keyCode:0];
            [NSApp postEvent:e atStart:NO];
        }
        say([NSString stringWithFormat:@"typed %@", line]);
    } else if ([c isEqualToString:@"menu"] && [f count] > 1) {
        NSString *path = [[f subarrayWithRange:NSMakeRange(1, [f count] - 1)] componentsJoinedByString:@" "];
        NSMenuItem *it = menu_item([NSApp mainMenu], [path componentsSeparatedByString:@"/"]);
        if (it && [it menu]) [[it menu] performActionForItemAtIndex:[[it menu] indexOfItem:it]];
        say([NSString stringWithFormat:@"menu %@ %@", path, it ? @"done" : @"not found"]);
    } else {
        say([NSString stringWithFormat:@"unknown command: %@", line]);
    }
}

void x86_ctl_start(void)
{
    const char *d = getenv("X86RT_CTL");
    if (!d) return;
    g_dir = [[NSString alloc] initWithUTF8String:d];
    g_timer = [NSTimer timerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *t) {
        NSString *p = [g_dir stringByAppendingPathComponent:@"cmd"];
        NSString *s = [NSString stringWithContentsOfFile:p encoding:NSUTF8StringEncoding error:nil];
        if (!s) return;
        [[NSFileManager defaultManager] removeItemAtPath:p error:nil];
        for (NSString *line in [s componentsSeparatedByString:@"\n"])
            if ([line length]) run(line);
    }];
    [[NSRunLoop mainRunLoop] addTimer:g_timer forMode:NSRunLoopCommonModes];
}

#ifdef CTL_INJECT
__attribute__((constructor)) static void ctl_inject(void) { x86_ctl_start(); }
#endif
