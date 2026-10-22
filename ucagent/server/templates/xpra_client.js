/** UCAgent's automatic application surface, using the installed Xpra protocol and renderer. */
"use strict";
// Xpra's libraries expect these shared globals; connection settings never come from query parameters.
var client, default_settings={}, float_menu_width=0, float_menu_item_size=24, float_menu_padding=8;
var clog=(...args)=>console.debug(...args), cdebug=(...args)=>console.debug(...args);

(() => {
    let unloading=false,closed=false;
    const windows=new Map(),attempt=new URL(location.href).searchParams.get("attempt");
    const consoleMode=window.frameElement?.dataset.mode==="console";
    const menu=document.querySelector("#clipboard-menu"),dialog=document.querySelector("#clipboard-dialog");
    const clipboardText=document.querySelector("#clipboard-text"),selections=new Map();
    let localClipboard="",menuWindow=null,noticeTimer=null,selectionName=consoleMode?"PRIMARY":"CLIPBOARD";
    /** Return the current remote text selection without reading the browser clipboard. */
    const selectedText=()=>selections.get(selectionName)||"";
    /** Report clipboard outcomes without replacing the connection status. */
    const clipboardNotice=message=>{
        const notice=document.querySelector("#clipboard-notice");
        clearTimeout(noticeTimer);notice.textContent=message;notice.hidden=false;
        noticeTimer=setTimeout(()=>{notice.hidden=true;},6000);
    };
    /** Restore remote keyboard capture after a local clipboard interaction. */
    const dismissClipboard=()=>{
        menu.hidden=true;
        if(!dialog.open&&client?.connected){
            client.capture_keyboard=true;
            // WebKit can otherwise retain the containing page's input focus.
            window.frameElement?.focus();document.querySelector("#screen").focus({preventScroll:true});
        }
    };
    /** Offer manual copy or paste when browser clipboard access is unavailable or denied. */
    const manualClipboard=(action,text="")=>{
        menu.hidden=true;client.capture_keyboard=false;
        document.querySelector("#clipboard-title").textContent=action==="copy"?"Copy selected text":"Paste text";
        document.querySelector("#clipboard-help").textContent=action==="copy"
            ?"The browser could not write to the clipboard. Copy the selected text below with your browser's Copy command."
            :"Paste text below using your browser's Paste command, then select Paste into terminal. This also works when browser clipboard access is unavailable. Text is sent as entered; a newline may execute a command.";
        clipboardText.readOnly=action==="copy";clipboardText.value=text;
        document.querySelector("#clipboard-submit").hidden=action==="copy";
        if(!dialog.open)dialog.showModal();clipboardText.focus();if(action==="copy")clipboardText.select();
    };
    /** Bound browser permission waits so users can always reach manual clipboard controls. */
    const browserClipboard=async(action,text)=>{
        let timer;
        try{
            return await Promise.race([navigator.clipboard[action](text),new Promise((resolve,reject)=>{
                timer=setTimeout(()=>reject(new Error("Clipboard permission was not granted.")),3000);
            })]);
        }finally{clearTimeout(timer);}
    };
    /** Publish explicit local text and ask the focused terminal to paste its X11 selection. */
    const pasteText=text=>{
        if(!client?.connected||!client.clipboard_enabled)throw new Error("Clipboard is unavailable. Reconnect or check the session's clipboard settings.");
        const win=client.id_to_window[menuWindow]||client.id_to_window[client.focused_wid];
        if(!win)throw new Error("Select an application window before pasting.");
        if(!text){clipboardNotice("The clipboard is empty.");return;}
        localClipboard=text;client.clipboard_buffer=text;client.clipboard_pending=false;
        // xterm pastes PRIMARY with Shift+Insert; other terminals may read CLIPBOARD.
        const bytes=Utilities.StringToUint8(text);
        for(const selection of ["CLIPBOARD","PRIMARY"]){
            client.send([PACKET_TYPES.clipboard_token,selection,["UTF8_STRING","text/plain"],
                "UTF8_STRING","UTF8_STRING",8,"bytes",bytes,true,true,true]);
        }
        // X11 selection delivery is asynchronous. Use Xpra's clipboard input barrier so
        // a following Enter cannot reach the application ahead of its pasted text.
        client.clipboard_delayed_event_time=performance.now()+CLIPBOARD_EVENT_DELAY;
        client.set_focus(win);
        for(const pressed of [true,false]){
            client.send([PACKET_TYPES.key_action,win.wid,"Insert",pressed,["shift"],0,"",45,0]);
        }
        dismissClipboard();clipboardNotice("Text pasted into the terminal.");
    };
    /** Execute an explicit copy/paste gesture and surface denied clipboard access. */
    const clipboardAction=async action=>{
        if(!client?.connected||!client.clipboard_enabled){clipboardNotice("Clipboard is unavailable. Reconnect or check the session's clipboard settings.");return;}
        if(action==="copy"){
            const text=selectedText();
            if(!text){dismissClipboard();clipboardNotice("No text is selected. Drag over terminal text first.");return;}
            try{await browserClipboard("writeText",text);dismissClipboard();clipboardNotice("Selection copied.");}
            catch{manualClipboard("copy",text);}
        }else{
            try{pasteText(await browserClipboard("readText"));}
            catch{manualClipboard("paste");}
        }
    };
    /** Keep bare console right clicks local so xterm does not alter the selected range. */
    const consoleRightClick=event=>consoleMode&&event.button===2&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.shiftKey
        &&event.target.closest(".window:not(.override-redirect):not(.tray) canvas");
    for(const type of ["mousedown","mouseup"]){
        document.addEventListener(type,event=>{
            if(consoleRightClick(event)){event.preventDefault();event.stopPropagation();}
        },true);
    }
    document.addEventListener("contextmenu",event=>{
        if(dialog.contains(event.target))return;
        event.preventDefault();
        if(!consoleRightClick(event)||!client?.connected)return;
        menuWindow=Number(event.target.closest(".window").id);
        client.capture_keyboard=false;menu.hidden=false;
        document.querySelector("#clipboard-copy").disabled=!selectedText();
        menu.style.left=Math.max(0,Math.min(event.clientX,innerWidth-menu.offsetWidth))+"px";
        menu.style.top=Math.max(0,Math.min(event.clientY,innerHeight-menu.offsetHeight))+"px";
        document.querySelector("#clipboard-paste").focus();
    });
    document.addEventListener("mousedown",event=>{if(!menu.hidden&&!menu.contains(event.target))dismissClipboard();},true);
    document.querySelector("#clipboard-copy").onclick=()=>clipboardAction("copy");
    document.querySelector("#clipboard-paste").onclick=()=>clipboardAction("paste");
    document.querySelector("#clipboard-manual").onclick=()=>manualClipboard("paste");
    document.querySelector("#clipboard-cancel").onclick=()=>{dialog.close();dismissClipboard();};
    document.querySelector("#clipboard-submit").onclick=()=>{
        try{
            pasteText(clipboardText.value);dialog.close();
            // The dialog's close event is queued; restore focus before the next keystroke.
            dismissClipboard();
        }catch(error){clipboardNotice(error.message);}
    };
    dialog.addEventListener("close",dismissClipboard);
    // The manual dialog uses ordinary browser clipboard events and never forwards its keys.
    for(const type of ["keydown","keyup"]){
        document.addEventListener(type,event=>{
            if(dialog.open)return;
            if(event.key==="Escape"&&!menu.hidden){event.preventDefault();event.stopPropagation();dismissClipboard();return;}
            const shortcut=consoleMode&&(event.metaKey||event.ctrlKey&&event.shiftKey)&&!event.altKey;
            if(shortcut&&["c","v"].includes(event.key.toLowerCase())){
                event.preventDefault();event.stopPropagation();
                if(type==="keydown"&&!event.repeat)clipboardAction(event.key.toLowerCase()==="c"?"copy":"paste");
            }
        },true);
    }
    document.addEventListener("copy",event=>{
        if(dialog.open||!consoleMode)return;
        event.preventDefault();event.stopPropagation();event.clipboardData?.setData("text/plain",selectedText());
    },true);
    document.addEventListener("paste",event=>{
        if(dialog.open||!consoleMode)return;
        event.preventDefault();event.stopPropagation();
        try{pasteText(event.clipboardData?.getData("text/plain")||"");}catch(error){clipboardNotice(error.message);}
    },true);
    const report=(type,message="",extra={})=>{
        if(!unloading)window.parent.postMessage({source:"ucagent-xpra",attempt,type,message,...extra},location.origin);
    };
    const close=reason=>{
        if(closed)return;
        closed=true;
        // A rejected or superseded viewer must not repeatedly reclaim the session.
        const code=String(reason||"").split("\n",1)[0].trim().toLowerCase();
        const permanent=["new client","session busy","session locked","authentication failed","permission error",
            "server shutdown","server exit","session not found"];
        report("closed",reason||"The display connection was interrupted. Reconnecting automatically…",{retryable:!permanent.includes(code),takenOver:code==="new client"});
    };
    const reportWindows=()=>{
        window.parent.postMessage({source:"ucagent-xpra",attempt,type:"windows",windows:[...windows.values()]},location.origin);
    };
    window.addWindowListItem=(win,id,title)=>{
        windows.set(id,{id,title});reportWindows();
        // A console is a work surface: use its available area from the first frame.
        if(windows.size===1&&window.frameElement?.dataset.mode==="console"&&win.resizable){
            requestAnimationFrame(()=>{if(client.id_to_window[id]===win)win.set_maximized(true);});
        }
    };
    window.removeWindowListItem=id=>{windows.delete(id);reportWindows();};
    window.noWindowList=()=>{};
    window.addEventListener("message",event=>{
        if(event.origin!==location.origin||event.source!==window.parent||event.data?.source!=="ucagent-xpra-view")return;
        if(event.data.type==="focus"){
            const win=client?.id_to_window[event.data.id];
            if(win){win.set_minimized(false);win.focus();}
        }
    });
    window.addEventListener("pagehide",()=>{unloading=true;if(client)client.close();});
    window.addEventListener("error",event=>{
        report("error","The application display encountered an error. Select Reconnect; if it persists, check the installed Xpra HTML5 resources. "+event.message);
    });
    async function start(){
        // Keep workers and their relative imports inside the authenticated session asset path.
        const scripts=[
            "lib/jquery.js","lib/jquery-ui.js","lib/jquery.ba-throttle-debounce.js",
            "lib/jquery-transform-draggable.js","lib/rencode.js","lib/lz4.js","lib/brotli_decode.js",
            "lib/hmac.js","lib/jsmpeg.js","lib/aurora/aurora.js","lib/aurora/aurora-xpra.js",
            "lib/web-streams-ponyfill.es6.js","lib/StreamSaver.js","lib/FileSaver.js","lib/detect-zoom.js",
            "Utilities.js","Keycodes.js","Protocol.js","WebTransport.js","Constants.js","Window.js",
            "Notifications.js","MediaSourceUtil.js","RgbHelpers.js","VideoDecoder.js",
            "OffscreenDecodeWorkerHelper.js","lib/slick.js","Client.js"
        ];
        for(const name of scripts){
            await new Promise((resolve,reject)=>{
                const script=document.createElement("script");script.src="js/"+name;
                script.onload=resolve;script.onerror=()=>reject(new Error("Missing HTML5 resource: "+name+". Install the official xpra-html5 client or correct cmd_api.xpra.html_dir."));
                document.head.append(script);
            });
        }
        SHOW_START_MENU=false;
        client=new XpraClient("screen");
        client.host=location.hostname;
        client.port=location.port||(location.protocol==="https:"?443:80);
        client.ssl=location.protocol==="https:";
        client.path=new URL(".",location.href).pathname;
        client.username="ucagent";
        // Console shortcuts are handled locally; keep physical Control for terminal signals.
        if(consoleMode)client.swap_keys=false;
        client.remote_logging=false;
        client.clipboard_enabled=true;
        // Only explicit clipboard gestures may read local data; never prompt on connection.
        client.clipboard_poll=false;
        client.clipboard_preferred_format="text/plain";
        client.printing=false;
        client.file_transfer=false;
        client.audio_enabled=false;
        client.audio_mediasource_enabled=false;
        client.audio_aurora_enabled=false;
        client.open_url=false;
        // New viewers take ownership. Displaced viewers wait for an explicit reclaim.
        client.sharing=false;
        client.steal=true;
        // The containing page owns retries so every attempt rechecks session access and state.
        client.reconnect=false;
        client.on_connection_progress=(state,details,progress)=>{
            if(progress<100)report("progress",state==="Initializing"?"Preparing the application display…":"Connecting securely to your application…");
        };
        client.on_connect=()=>{client.capture_keyboard=true;report("connected");};
        client.callback_close=close;
        // The private socket has no separate Xpra password. An unexpected challenge is an
        // operator configuration error; never open a second login form or accept URL secrets.
        client.password_prompt_fn=()=>{
            closed=true;
            report("error","The session unexpectedly requested separate Xpra authentication. Check the session logs and restart it from Sessions.");
            client.close();
        };
        client.init(false);
        if(consoleMode){
            // Negotiate PRIMARY even in modern browsers: terminal selections are not CLIPBOARD.
            const clipboardCaps=client._get_clipboard_caps;
            client._get_clipboard_caps=function(){return {...clipboardCaps.call(this),selections:["CLIPBOARD","PRIMARY"]};};
            // Cache remote text only. Browser clipboard access requires a user action.
            client.packet_handlers[PACKET_TYPES.clipboard_token]=packet=>{
                if(!client.clipboard_enabled)return;
                const selection=packet[1],type=String(packet[4]||"").toLowerCase();
                let text="";
                if(packet.length>=8&&packet[5]===8&&(type.includes("text")||type.includes("string"))){
                    text=typeof packet[7]==="string"?packet[7]:Utilities.Uint8ToString(packet[7]);
                }
                selections.set(selection,text);selectionName=selection;
                client.clipboard_buffer=selectedText();client.clipboard_pending=false;
                document.querySelector("#clipboard-copy").disabled=!selectedText();
            };
            client.packet_handlers[PACKET_TYPES.clipboard_request]=packet=>{
                client.send_clipboard_string(packet[1],packet[2],localClipboard,"UTF8_STRING");
            };
        }else client.init_clipboard();
        client.connect();
        document.addEventListener("visibilitychange",()=>{
            if(client.connected){if(document.hidden)client.suspend();else client.resume();}
        });
    }
    start().catch(error=>report("error",error.message));
})();
