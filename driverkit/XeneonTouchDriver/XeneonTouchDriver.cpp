// XeneonTouchDriver.cpp
// Phase 1: claim Interface 0, confirm driver loads and outbids AppleUserHIDDevice.
// Feature report / multitouch dispatch added once driver is confirmed loading.

#include <DriverKit/IOLib.h>
#include <HIDDriverKit/IOUserUSBHostHIDDevice.h>
#include "XeneonTouchDriver.h"

#if __has_include(<os/log.h>)
#include <os/log.h>
#define DLOG(fmt, ...) os_log(OS_LOG_DEFAULT, "XeneonTouchDriver: " fmt, ##__VA_ARGS__)
#else
#define DLOG(fmt, ...) do {} while(0)
#endif

kern_return_t XeneonTouchDriver::Start_Impl(IOService * provider)
{
    DLOG("Start — claiming Interface 0");
    kern_return_t ret = Start(provider, SUPERDISPATCH);
    DLOG("Start result: 0x%08X", ret);
    return ret;
}

kern_return_t XeneonTouchDriver::Stop_Impl(IOService * provider)
{
    DLOG("Stop");
    return Stop(provider, SUPERDISPATCH);
}
