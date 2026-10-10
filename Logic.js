// Contract v1. Shared by QML and Node tests; never coerce absent metrics to zero.
var toolIds = ['hermes', 'codex', 'claude', 'antigravity', 'opencode', 'commandcode'];
var toolNames = ['Hermes', 'Codex', 'Claude Code', 'Antigravity', 'OpenCode', 'Command Code'];
var series = ['input', 'output', 'cache_read', 'cache_write'];
var seriesNames = ['Input', 'Output', 'Cache read', 'Cache write'];
var seriesIcons = ['\uf090', '\uf08b', '\uf019', '\uf0c7'];
function barCenter(index,width,count,padding) {
    return padding+(index+0.5)*Math.max(1,width-padding*2)/Math.max(1,count);
}
function displayDates(value) {
    if (value === null || value === undefined || value === '') return '—';
    return String(value).replace(/\b(\d{4})-(\d{2})-(\d{2})(?!\d)/g,'$3/$2/$1');
}
function axisLabel(bucket,rangeKey) {
    var label=String(bucket.label || '');
    if (rangeKey === 'today') return label;
    var match=/^(\d{4})-(\d{2})-(\d{2})$/.exec(label);
    if (!match) return '—';
    if (rangeKey === 'all') return displayDates(label);
    // The producer's label is already in its configured local timezone.
    // Parse the calendar date as UTC to avoid shifting its weekday on this host.
    return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][new Date(Date.UTC(Number(match[1]),Number(match[2])-1,Number(match[3]))).getUTCDay()];
}
function axisTicks(rows,rangeKey,width,padding,minSpacing) {
    var count=rows.length;
    if (!count) return [];
    var visible=Math.min(count,Math.max(1,Math.floor(Math.max(1,width-padding*2)/minSpacing)));
    var result=[];
    for (var i=0;i<visible;i++) {
        var index=visible === 1 ? Math.floor((count-1)/2) : Math.round(i*(count-1)/(visible-1));
        result.push({index:index,x:barCenter(index,width,count,padding),label:axisLabel(rows[index],rangeKey)});
    }
    return result;
}
function barBucket(x,width,count,padding) {
    if (count < 1) return -1;
    return Math.max(0,Math.min(count-1,Math.floor((x-padding)/Math.max(1,width-padding*2)*count)));
}
function nearestBucket(x,width,count,padding) {
    if (count < 1) return -1;
    return Math.max(0,Math.min(count-1,Math.round((x-padding)/Math.max(1,width-padding*2)*(count-1))));
}
function focusOpacity(index,selected,focused) { return !focused || index === selected ? 1 : 0.18; }
function tooltipRows(bucket) {
    var b = bucket || {};
    return [{icon:'\uf1ec',name:'Total',value:format(b.total)}].concat(series.map(function(key,i) {
        return {icon:seriesIcons[i],name:seriesNames[i],value:format(b[key])};
    }));
}
function quotaFraction(q) {
    if (known(q.used_percent)) return Math.min(1,q.used_percent/100);
    if (known(q.remaining_percent) && q.remaining_percent <= 100) return 1-q.remaining_percent/100;
    return null;
}
function quotaWindow(q) {
    var label=String(q.label || '').toLowerCase();
    if (q.window_minutes === 10080 || /weekly|7 days|7-day|168 hours/.test(label)) return 'week';
    if (q.window_minutes === 300 || /5[- ]?h|5 hours|300 minutes/.test(label)) return '5h';
    return '';
}
function quotaRows(tool) {
    var raw=(tool.quotas || []).filter(function(q) { return tool.id !== 'codex' || quotaWindow(q) === 'week'; });
    var result=raw.map(function(q) {
        var row={}; Object.keys(q).forEach(function(k) { row[k]=q[k]; });
        var win=quotaWindow(q);
        row.label=(q.model ? (q.model_scope === 'shared_group' && q.model === 'Claude and GPT models' ? 'Opus / Sonnet / GPT-OSS' : q.model)+' · ' : '')+(win === 'week' ? 'Weekly limit' : win === '5h' ? '5-hour limit' : q.label || 'Provider limit');
        return row;
    });
    function missing(win,model,label) {
        if (!raw.some(function(q) { return quotaWindow(q) === win && (model ? String(q.model || q.label || '').toLowerCase().indexOf(model.toLowerCase()) >= 0 : !q.model); }))
            result.push({label:label,model:model || null,window_minutes:win === 'week' ? 10080 : 300,used_percent:null,remaining_percent:null,resets_at:null,observed_at:null,status:'unavailable',source:'No verified provider quota source'});
    }
    if (tool.id === 'antigravity' && raw.some(function(q) { return q.model_scope === 'shared_group'; })) {
        var groups=[];
        raw.forEach(function(q) { if (q.model && groups.indexOf(q.model)<0) groups.push(q.model); });
        groups.forEach(function(model) { missing('5h',model,model+' · 5-hour limit'); missing('week',model,model+' · Weekly limit'); });
        return result;
    }
    if (tool.id === 'codex') missing('week',null,'Weekly limit');
    if (tool.id === 'commandcode' || tool.id === 'claude' || tool.id === 'antigravity') {
        missing('5h',null,'5-hour limit'); missing('week',null,'Weekly limit');
    }
    if (tool.id === 'antigravity') ['Opus','ChatGPT'].forEach(function(model) {
        missing('5h',model,model+' · 5-hour limit'); missing('week',model,model+' · Weekly limit');
    });
    return result;
}
function known(v) { return typeof v === 'number' && isFinite(v) && v >= 0; }
function emptyTool(id) {
    return {id:id, name:toolNames[toolIds.indexOf(id)] || id, installed:false,
        state:'unavailable', activity:'unknown', last_model:null, active_models:[],
        totals:{today:null,week:null,all:null}, days:[], ranges:{}, quotas:[],
        coverage:{incomplete:true,earliest:null,note:'No local records available'}, last_source_at:null};
}
function parseSnapshot(text) {
    var s;
    try { s = JSON.parse(text); } catch (_) { s = null; }
    if (!s || s.version !== 1 || !Array.isArray(s.tools))
        return {version:1,settings:{},tools:toolIds.map(emptyTool),updated_at:null,unavailable:true};
    var byId = {};
    s.tools.forEach(function(t) { if (t && toolIds.indexOf(t.id) >= 0) byId[t.id] = t; });
    s.tools = toolIds.map(function(id) {
        var t = emptyTool(id), src = byId[id];
        if (src) Object.keys(src).forEach(function(k) { if (src[k] !== null) t[k] = src[k]; });
        return t;
    });
    s.settings = s.settings || {};
    return s;
}
function pickTool(snapshot,id) {
    var tools = snapshot.tools || [];
    for (var i=0;i<tools.length;i++) if (tools[i].id === id) return tools[i];
    return emptyTool(id);
}
function installedTools(snapshot) { return (snapshot.tools || []).filter(function(t) { return t.installed === true; }); }
function selectInstalled(snapshot, preferred) {
    var tools = installedTools(snapshot);
    return tools.some(function(t) { return t.id === preferred; }) ? preferred : (tools.length ? tools[0].id : '');
}
function openTool(settings) { return toolIds.indexOf(settings.default_tool) >= 0 ? settings.default_tool : 'hermes'; }
function format(v) {
    if (!known(v)) return '—';
    if (v >= 1000000000) return (v/1000000000).toFixed(1)+'B';
    if (v >= 1000000) return (v/1000000).toFixed(1)+'M';
    if (v >= 1000) return (v/1000).toFixed(1)+'k';
    return String(v);
}
function exact(v) { return known(v) ? String(v) : '—'; }
function duration(seconds) {
    if (!known(seconds)) return '—';
    if (seconds >= 86400) return Math.floor(seconds/86400)+'d';
    if (seconds >= 3600) return Math.floor(seconds/3600)+'h';
    if (seconds >= 60) return Math.floor(seconds/60)+'m';
    return Math.floor(seconds)+'s';
}
function dailyRows(days,range,key) {
    if (key === 'week') return days;
    var buckets = range.buckets || [];
    if (key === 'all') return buckets; // Contract producer supplies daily all-time buckets.
    return days.filter(function(day) {
        return buckets.some(function(b) { return known(day.start) && known(day.end) && known(b.start) && b.start >= day.start && b.start < day.end; });
    });
}
function barValues(rows, keys) {
    return rows.map(function(b) {
        var values = keys.map(function(k) { return b[k]; }).filter(known);
        return values.length ? values.reduce(function(sum,v) { return sum+v; },0) : null;
    });
}
function peak(rows, keys) {
    var max = 1;
    rows.forEach(function(b) { keys.forEach(function(k) { if (known(b[k])) max = Math.max(max,b[k]); }); });
    return max;
}
function chartPoints(rows,key,width,height,max,logScale) {
    return rows.map(function(b,i) {
        return known(b[key]) ? {x:rows.length > 1 ? i*width/(rows.length-1) : width/2, y:height*(1-(logScale ? Math.log(1+b[key])/Math.log(1+Math.max(1,max)) : b[key]/Math.max(1,max)))} : null;
    });
}
function ranked(models) {
    return models.slice().sort(function(a,b) { return (known(b.total) ? b.total : -1) - (known(a.total) ? a.total : -1); });
}
function modelRows(range, expanded) {
    var grouped = Object.create(null);
    (range.models || []).forEach(function(row) {
        var name = row.model || 'Unattributed';
        if (!grouped[name]) grouped[name] = {model:name, total:0, providers:[]};
        var g = grouped[name];
        g.total = known(g.total) && known(row.total) ? g.total + row.total : null;
        var provider = row.provider || 'Unknown route';
        if (g.providers.indexOf(provider) < 0) g.providers.push(provider);
    });
    var rows = ranked(Object.keys(grouped).map(function(key) { return grouped[key]; }));
    return expanded ? rows : rows.slice(0,3);
}
function tooltip(b) {
    if (!b) return 'No observation';
    return displayDates(b.interval || b.label || b.model || '') + '\nTotal: ' + format(b.total) + '\n' +
        series.map(function(k,i) { return seriesNames[i]+': '+format(b[k]); }).join('\n');
}
