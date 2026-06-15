import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSET = path.resolve(__dirname, '../assets');

const C = {
  ink: '#162238', muted: '#637089', paper: '#EEF2F4', card: '#F8FAF8', line: '#D4DCE8',
  navy: '#132033', navy2: '#0F1A2B', cyan: '#37A8B9', blue: '#4F73D9', green: '#72B86B',
  orange: '#EF9B3A', red: '#D95F59', purple: '#7669D8', soft: '#E8EEF3'
};
const FONT = 'Hiragino Sans GB';
const MONO = 'SF Mono';
const W = 1600, H = 900;

function p(name) { return path.join(ASSET, name); }
function line(color=C.line, width=1) { return { style:'solid', fill: color, width }; }
function noLine() { return { style:'solid', fill:'#00000000', width:0 }; }
function box(ctx, slide, x,y,w,h, fill=C.card, stroke=C.line, width=1) { return ctx.addShape(slide,{x,y,w,h,fill,line:line(stroke,width)}); }
function txt(ctx, slide, text, x,y,w,h, opts={}) {
  return ctx.addText(slide,{text,x,y,w,h,fontSize:opts.size??24,color:opts.color??C.ink,bold:opts.bold??false,typeface:opts.mono?MONO:FONT,align:opts.align??'left',valign:opts.valign??'top',insets:opts.insets??{left:0,right:0,top:0,bottom:0},fill:opts.fill??'#00000000',line:opts.line??noLine()});
}
async function bg(ctx, slide, num, section='期末汇报') {
  await ctx.addImage(slide,{path:p('paper_texture.png'),x:0,y:0,w:W,h:H,fit:'cover',alt:'paper texture'});
  ctx.addShape(slide,{x:0,y:0,w:W,h:H,fill:'#EEF2F4DD',line:noLine()});
  ctx.addShape(slide,{x:0,y:0,w:W,h:92,fill:C.navy,line:noLine()});
  ctx.addShape(slide,{x:0,y:92,w:W,h:5,fill:C.cyan,line:noLine()});
  txt(ctx,slide,section,58,24,500,38,{size:20,color:'#AEBBD0'});
  txt(ctx,slide,String(num).padStart(2,'0'),1480,25,70,36,{size:21,color:'#AEBBD0',align:'right'});
}
function title(ctx, slide, headline, sub='') {
  txt(ctx,slide,headline,58,120,1020,58,{size:36,bold:true,color:C.ink});
  if(sub) txt(ctx,slide,sub,60,178,1120,36,{size:21,color:C.muted});
}
function claim(ctx, slide, text, x=60, y=815, w=1480) {
  box(ctx,slide,x,y,w,44,'#E6EEF2', '#C8D5E2', 1);
  txt(ctx,slide,text,x+18,y+10,w-36,24,{size:17,color:C.ink});
}
function kpi(ctx, slide, value, label, x,y,w=260,color=C.cyan) {
  box(ctx,slide,x,y,w,128,'#F8FAF8','#CED8E4',1);
  ctx.addShape(slide,{x,y,w:8,h:128,fill:color,line:noLine()});
  txt(ctx,slide,value,x+24,y+24,w-40,42,{size:34,bold:true,color});
  txt(ctx,slide,label,x+24,y+74,w-40,34,{size:17,color:C.muted});
}
function bulletList(ctx, slide, items, x,y,w, gap=44, size=21) {
  items.forEach((it,i)=>{ const yy=y+i*gap; ctx.addShape(slide,{x,y:yy+8,w:9,h:9,fill:it.color||C.cyan,line:noLine()}); txt(ctx,slide,it.text||it,x+24,yy,w-24,34,{size,color:C.ink}); });
}
function pill(ctx, slide, text, x,y,w,color=C.cyan) { box(ctx,slide,x,y,w,38,'#F8FAF8',color,1); txt(ctx,slide,text,x+14,y+8,w-28,22,{size:15,color}); }
function imageCard(ctx, slide, img, x,y,w,h, label='', fit='contain') {
  box(ctx,slide,x,y,w,h,'#F8FAF8','#CED8E4',1);
  return ctx.addImage(slide,{path:p(img),x:x+10,y:y+10,w:w-20,h:h-20,fit,alt:label||img});
}
function sectionLabel(ctx, slide, text, x,y,color=C.cyan) { txt(ctx,slide,text,x,y,420,28,{size:19,bold:true,color}); }
function statTable(ctx, slide, rows, x,y,w, cols) {
  const rowH=48; box(ctx,slide,x,y,w,rowH*(rows.length+1),'#F8FAF8','#CFD9E5',1);
  let cx=x; cols.forEach(c=>{ txt(ctx,slide,c.label,cx+12,y+14,c.w-24,22,{size:15,bold:true,color:C.muted}); cx+=c.w; });
  rows.forEach((r,i)=>{ const yy=y+rowH*(i+1); ctx.addShape(slide,{x,y:yy,w,h:1,fill:'#DDE5EE',line:noLine()}); let xx=x; cols.forEach(c=>{ txt(ctx,slide,String(r[c.key]),xx+12,yy+14,c.w-24,22,{size:16,color:c.color?c.color(r):C.ink,bold:c.bold??false}); xx+=c.w; }); });
}
function nodes(ctx, slide, arr) { arr.forEach(n=>{ box(ctx,slide,n.x,n.y,n.w,n.h,'#F8FAF8',n.color,2); ctx.addShape(slide,{x:n.x,y:n.y,w:8,h:n.h,fill:n.color,line:noLine()}); txt(ctx,slide,n.t,n.x+24,n.y+20,n.w-40,30,{size:22,bold:true,color:C.ink}); txt(ctx,slide,n.s,n.x+24,n.y+58,n.w-42,48,{size:17,color:C.muted}); }); }
function simpleArrow(ctx, slide, x1,y1,x2,y2,color=C.blue) { ctx.addShape(slide,{geometry:'rect',x:x1,y:y1,w:x2-x1,h:4,fill:color,line:noLine()}); ctx.addShape(slide,{geometry:'triangle',x:x2-2,y:y2-8,w:18,h:18,fill:color,line:noLine()}); }

export async function renderSlide(presentation, ctx, idx) {
  const slide = presentation.slides.add();
  await bg(ctx, slide, idx);
  switch(idx) {
    case 1: {
      ctx.addShape(slide,{x:0,y:0,w:W,h:H,fill:'#132033EE',line:noLine()});
      await ctx.addImage(slide,{path:p('paper_texture.png'),x:0,y:0,w:W,h:H,fit:'cover',alt:'paper texture'});
      ctx.addShape(slide,{x:0,y:0,w:W,h:H,fill:'#132033DD',line:noLine()});
      txt(ctx,slide,'面向智能家居的边缘自治 Agent 系统',70,180,1180,68,{size:44,bold:true,color:'#FFFFFF'});
      txt(ctx,slide,'期末汇报：通信异常、优先级调度、状态可信度与容错验证',74,262,1120,38,{size:24,color:'#C9D5E8'});
      ['MQTT 实际闭环','148 次仿真运行','4452 条任务记录','7 张实验图表'].forEach((t,i)=>pill(ctx,slide,t,76+i*250,350,210,i===0?C.cyan:i===1?C.green:i===2?C.orange:C.purple));
      txt(ctx,slide,'研究主线',78,514,180,26,{size:20,color:'#8DE5FF'});
      txt(ctx,slide,'在不稳定边缘环境下，让智能家居 Agent 不只是“触发规则”，而是能判断状态可信度、安排任务优先级，并确认设备是否真正执行。',78,552,1190,72,{size:25,color:'#EEF4FF'});
      txt(ctx,slide,'Edge Agent · Home Assistant · MQTT · Reliability Evaluation',80,805,900,28,{size:18,color:'#AEBBD0'});
      break;
    }
    case 2: {
      title(ctx,slide,'期末任务要求转化为研究产出','从“系统能跑”扩展到“机制可解释、实验可复现、结果可量化”');
      const rows=[
        {a:'研究背景',b:'智能家居边缘自治，不依赖云端完成核心判断',c:'背景页 + 系统架构'},
        {a:'研究方案',b:'规则、优先级、状态过期、ACK 确认与重试',c:'机制设计页'},
        {a:'研究结果',b:'延迟、丢包、离线、消融、真实 MQTT 验证',c:'CSV + 图表 + 截图'},
        {a:'提交材料',b:'PPT、录屏、代码、实验结果文件',c:'完整目录可复现'},
      ];
      statTable(ctx,slide,rows,90,260,1420,[{key:'a',label:'要求维度',w:220},{key:'b',label:'本项目对应内容',w:770},{key:'c',label:'汇报证据',w:430}]);
      kpi(ctx,slide,'完整闭环','传感器 → Agent → 设备 → 可视化',110,600,330,C.cyan);
      kpi(ctx,slide,'量化实验','响应时间 / 成功率 / 等待时间',470,600,330,C.green);
      kpi(ctx,slide,'真实验证','Docker + MQTT + edge_agent.py',830,600,330,C.orange);
      kpi(ctx,slide,'可复现','CSV / 图表 / 脚本均保留',1190,600,330,C.purple);
      claim(ctx,slide,'本次期末汇报围绕“边缘自治 Agent 的可靠控制能力”组织，而不是简单展示 Home Assistant 页面。');
      break;
    }
    case 3: {
      title(ctx,slide,'研究问题：边缘环境下普通自动化规则不够稳定','延迟、丢包和设备离线会让“发出命令”不等于“完成控制”');
      bulletList(ctx,slide,[
        {text:'状态不可靠：传感器可能长时间未更新，旧状态会导致误判。',color:C.red},
        {text:'任务无优先：报警、安防与舒适性任务混在一起，关键任务可能排队。',color:C.orange},
        {text:'执行不可知：设备可能离线或命令丢失，普通规则无法确认结果。',color:C.purple},
        {text:'缺少量化：只看页面状态变化，无法说明稳定性提升来自哪里。',color:C.blue},
      ],100,260,760,56,23);
      const problem=[
        {x:980,y:240,w:410,h:96,t:'普通规则',s:'if 条件成立 → 直接发布命令',color:C.blue},
        {x:980,y:380,w:410,h:96,t:'不稳定链路',s:'延迟、丢包、设备离线会打断闭环',color:C.orange},
        {x:980,y:520,w:410,h:96,t:'结果不可确认',s:'无法区分“已发送”和“已执行”',color:C.red},
      ]; nodes(ctx,slide,problem); simpleArrow(ctx,slide,1184,340,1184,380,C.orange); simpleArrow(ctx,slide,1184,480,1184,520,C.red);
      claim(ctx,slide,'核心问题定义：如何在弱网络和设备异常条件下，提高关键智能家居任务的完成稳定性。');
      break;
    }
    case 4: {
      title(ctx,slide,'总体方案：边缘自治 Agent 作为本地控制中枢','系统由真实 MQTT 演示闭环和可重复实验评估两部分组成');
      const ns=[
        {x:80,y:300,w:260,h:116,t:'传感器模拟',s:'温度、光照、门磁、PIR',color:C.cyan},
        {x:420,y:300,w:260,h:116,t:'MQTT Broker',s:'状态上报与命令下发',color:C.blue},
        {x:760,y:300,w:260,h:116,t:'边缘 Agent',s:'规则判断、队列、容错',color:C.green},
        {x:1100,y:300,w:260,h:116,t:'设备执行',s:'灯、空调、报警器反馈',color:C.orange},
      ]; nodes(ctx,slide,ns); simpleArrow(ctx,slide,340,356,420,356); simpleArrow(ctx,slide,680,356,760,356); simpleArrow(ctx,slide,1020,356,1100,356);
      box(ctx,slide,300,560,1000,120,C.navy2,'#33445F',1); txt(ctx,slide,'Home Assistant 可视化层',330,584,400,30,{size:24,bold:true,color:'#FFFFFF'}); txt(ctx,slide,'展示实体状态、辅助观察系统运行；核心决策仍在边缘 Agent 本地完成。',330,628,900,28,{size:20,color:'#C9D5E8'});
      kpi(ctx,slide,'Docker','Mosquitto + Home Assistant',130,710,300,C.cyan); kpi(ctx,slide,'Python','Agent / 传感器 / 设备模块',500,710,330,C.green); kpi(ctx,slide,'CSV','任务级指标与实验结果',900,710,300,C.orange);
      break;
    }
    case 5: {
      title(ctx,slide,'代码结构：从演示系统扩展为实验系统','核心代码保留模块边界，新增 experiments 作为期末评估层');
      const rows=[
        {m:'src/simulator/sensor_simulator.py',r:'虚拟环境状态生成',e:'周期发布温度、光照、门磁、PIR'},
        {m:'src/agent/edge_agent.py',r:'边缘决策核心',e:'规则判断、优先级任务、MQTT 控制'},
        {m:'src/device/device_executor.py',r:'设备执行反馈',e:'订阅命令并发布设备状态'},
        {m:'src/experiments/run_experiments.py',r:'批量可靠性实验',e:'延迟、丢包、离线、消融和图表'},
        {m:'src/experiments/real_mqtt_validation.py',r:'真实 MQTT 验证',e:'启动真实 Agent 并记录事件时间线'},
      ];
      statTable(ctx,slide,rows,70,230,1460,[{key:'m',label:'文件',w:520},{key:'r',label:'职责',w:320},{key:'e',label:'期末新增价值',w:620}]);
      claim(ctx,slide,'新增实验层不替代原有演示系统，而是把系统行为转化为可复现、可对比、可写进论文的证据。');
      break;
    }
    case 6: {
      title(ctx,slide,'真实平台截图：Home Assistant 与运行证据','截图来自当前本机运行环境，不是手绘界面');
      await imageCard(ctx,slide,'home_assistant_page.png',70,235,660,420,'Home Assistant screenshot','contain');
      await imageCard(ctx,slide,'evidence_screenshot.png',790,235,720,420,'runtime evidence screenshot','cover');
      txt(ctx,slide,'Home Assistant 已由 Docker 启动；当前截图显示平台入口。右侧证据截图包含 Docker 状态、真实 MQTT 事件与实验结果文件。',92,685,1380,50,{size:21,color:C.ink});
      claim(ctx,slide,'真实截图承担“系统确实运行”的证据角色；后续图表承担“机制是否有效”的量化分析角色。');
      break;
    }
    case 7: {
      title(ctx,slide,'Agent 机制深化：从规则触发到可靠控制','本次期末升级重点是让 Agent 具备判断、排队和确认能力');
      const ns=[
        {x:90,y:275,w:280,h:126,t:'规则判断',s:'门开 + 暗光；夜间门开 + 无人',color:C.blue},
        {x:430,y:275,w:280,h:126,t:'优先级队列',s:'报警 P1，舒适控制 P2/P3',color:C.green},
        {x:770,y:275,w:280,h:126,t:'状态可信度',s:'超时传感器状态不再直接使用',color:C.orange},
        {x:1110,y:275,w:280,h:126,t:'执行确认',s:'等待 ACK，超时重试并记录失败',color:C.red},
      ]; nodes(ctx,slide,ns);
      simpleArrow(ctx,slide,370,338,430,338); simpleArrow(ctx,slide,710,338,770,338); simpleArrow(ctx,slide,1050,338,1110,338);
      const rows=[
        {k:'普通规则',v:'满足条件后直接发布控制命令',l:'无法确认结果'},
        {k:'优先级调度',v:'关键任务优先派发',l:'降低报警等待时间'},
        {k:'状态过期',v:'忽略过旧传感器状态',l:'减少基于旧状态的误判'},
        {k:'失败重试',v:'等待设备 ACK，失败后重试',l:'提升任务成功率'},
      ]; statTable(ctx,slide,rows,170,520,1260,[{key:'k',label:'机制',w:240},{key:'v',label:'设计',w:560},{key:'l',label:'实验关注点',w:460}]);
      break;
    }
    case 8: {
      title(ctx,slide,'实验设计：用不稳定通信条件检验机制价值','所有实验结果由脚本实际运行生成 CSV，再由 CSV 绘制图表');
      const rows=[
        {e:'延迟实验',p:'0 / 100 / 200 / 500 / 800 ms',m:'平均响应时间'},
        {e:'丢包实验',p:'0% / 5% / 10% / 20% / 30% / 40%',m:'任务成功率'},
        {e:'策略对比',p:'普通规则 / 优先级 / 容错',m:'成功率、报警等待'},
        {e:'消融实验',p:'拆分优先级、过期判断、失败重试',m:'机制贡献'},
        {e:'真实 MQTT 验证',p:'Docker broker + edge_agent.py',m:'实际事件闭环'},
      ]; statTable(ctx,slide,rows,100,250,1400,[{key:'e',label:'实验组',w:260},{key:'p',label:'参数',w:700},{key:'m',label:'指标',w:440}]);
      kpi(ctx,slide,'148','次虚拟实验运行',170,620,270,C.cyan); kpi(ctx,slide,'4452','条任务级记录',500,620,270,C.green); kpi(ctx,slide,'25','条真实 MQTT 事件',830,620,270,C.orange); kpi(ctx,slide,'7','张结果图表',1160,620,270,C.purple);
      break;
    }
    case 9: {
      title(ctx,slide,'结果一：网络延迟越高，端到端响应时间越长','容错 Agent 通过 ACK 确认记录真实完成时间，而不是仅记录命令发送时间');
      await imageCard(ctx,slide,'01_avg_response_by_latency.png',150,230,1300,560,'latency chart','contain');
      claim(ctx,slide,'最大延迟从 0ms 增至 800ms 时，平均响应时间从约 434ms 增至约 2049ms，说明通信延迟直接影响用户感知响应。');
      break;
    }
    case 10: {
      title(ctx,slide,'结果二：丢包率上升会压低任务成功率','失败重试能缓冲中低丢包，但高丢包下成功率仍会下降');
      await imageCard(ctx,slide,'02_success_rate_by_drop.png',150,230,1300,560,'drop chart','contain');
      claim(ctx,slide,'丢包率升至 40% 时，容错 Agent 仍保持约 88.3% 的任务成功率，但响应时间与重试开销同步增加。');
      break;
    }
    case 11: {
      title(ctx,slide,'结果三：策略对比显示“成功率”和“等待时间”不是同一件事','优先级降低关键任务等待，容错机制提升整体成功率');
      await imageCard(ctx,slide,'03_agent_mode_comparison.png',130,220,1340,575,'mode comparison','contain');
      claim(ctx,slide,'在 300ms 延迟、15% 丢包、8% 离线条件下，容错 Agent 成功率约 96.5%；优先级机制将报警平均排队等待从约 1149ms 降至约 644ms。');
      break;
    }
    case 12: {
      title(ctx,slide,'结果四：报警任务需要单独评估及时性与完成率','安全任务不能只看平均成功率，还要看关键场景是否能触发');
      await imageCard(ctx,slide,'04_alarm_completion_rate.png',110,235,640,470,'alarm chart','contain');
      await imageCard(ctx,slide,'05_queue_wait_distribution.png',850,235,640,470,'queue distribution','contain');
      claim(ctx,slide,'报警完成率体现安全闭环是否成立；队列等待分布说明调度策略是否把关键任务提前处理。');
      break;
    }
    case 13: {
      title(ctx,slide,'消融实验：失败重试是成功率提升的主要来源','状态过期判断提升报警可靠性，重试机制显著提升整体完成率');
      await imageCard(ctx,slide,'06_ablation_study.png',130,215,1340,590,'ablation chart','contain');
      claim(ctx,slide,'完整容错 Agent 任务成功率约 96.1%；“优先级+重试”已达约 93.6%，说明 ACK 确认与重试是抵抗丢包/离线的关键机制。');
      break;
    }
    case 14: {
      title(ctx,slide,'消融实验关键数字：每个机制贡献不同','表格用于回答“到底是哪一部分起作用”');
      const rows=[
        {m:'普通规则',s:'66.5%',a:'71.7%',r:'1175ms',v:'基线，无确认'},
        {m:'优先级调度',s:'62.2%',a:'70.0%',r:'1120ms',v:'降低报警等待，但不抗丢包'},
        {m:'优先级+过期',s:'63.3%',a:'86.7%',r:'1129ms',v:'报警可靠性提升'},
        {m:'优先级+重试',s:'93.6%',a:'86.7%',r:'2503ms',v:'成功率显著提升，响应变慢'},
        {m:'完整容错 Agent',s:'96.1%',a:'91.7%',r:'2646ms',v:'稳定性最高'},
      ]; statTable(ctx,slide,rows,80,245,1440,[{key:'m',label:'版本',w:280},{key:'s',label:'任务成功率',w:210},{key:'a',label:'报警完成率',w:210},{key:'r',label:'平均响应',w:210},{key:'v',label:'结论',w:530}]);
      bulletList(ctx,slide,[
        {text:'优先级解决“先做哪个任务”的问题。',color:C.green},
        {text:'状态过期解决“状态是否可信”的问题。',color:C.orange},
        {text:'失败重试解决“命令是否真正执行”的问题。',color:C.red},
      ],160,590,1180,48,23);
      claim(ctx,slide,'系统结论不是“加功能越多越好”，而是稳定性和响应时间之间需要权衡。');
      break;
    }
    case 15: {
      title(ctx,slide,'真实 MQTT 验证：不只停留在离线仿真','实际 broker 上观察到传感器发布、Agent 派发和设备状态反馈');
      await imageCard(ctx,slide,'mqtt_validation_timeline.png',80,220,720,455,'mqtt timeline','contain');
      const rows=[
        {k:'Broker',v:'127.0.0.1:1883'},
        {k:'验证结果',v:'true'},
        {k:'观察事件',v:'25 条'},
        {k:'报警命令',v:'alarm=on 已派发'},
        {k:'灯光命令',v:'light=on 已派发'},
        {k:'设备反馈',v:'home/devices/state 已确认'},
      ]; statTable(ctx,slide,rows,880,250,560,[{key:'k',label:'项目',w:190},{key:'v',label:'真实验证结果',w:370}]);
      claim(ctx,slide,'大规模指标来自仿真实验；系统闭环则通过真实 Docker + MQTT + edge_agent.py 验证。');
      break;
    }
    case 16: {
      title(ctx,slide,'典型报警任务时间线：从异常状态到 ACK 确认','时间线来自任务级 CSV 中一条成功的 night-door-anomaly 记录');
      await imageCard(ctx,slide,'07_typical_event_timeline.png',110,230,1380,560,'typical timeline','contain');
      claim(ctx,slide,'该例展示容错 Agent 的完整闭环：触发并入队、首次派发、超时重试、设备 ACK 确认。');
      break;
    }
    case 17: {
      title(ctx,slide,'阶段性成果：从可演示系统到可评估系统','期末成果可以围绕三条贡献线展开');
      const rows=[
        {c:'系统实现',d:'完成传感器、MQTT、Agent、设备执行、Home Assistant 的本地闭环。'},
        {c:'机制设计',d:'加入优先级调度、状态过期判断、ACK 确认与超时重试。'},
        {c:'实验评估',d:'完成延迟、丢包、设备离线、策略对比、消融和真实 MQTT 验证。'},
      ]; statTable(ctx,slide,rows,130,260,1340,[{key:'c',label:'贡献',w:240},{key:'d',label:'内容',w:1100}]);
      kpi(ctx,slide,'96.1%','完整容错 Agent 成功率',180,575,300,C.green); kpi(ctx,slide,'88.3%','40% 丢包下成功率',520,575,300,C.cyan); kpi(ctx,slide,'644ms','优先级报警等待时间',860,575,300,C.orange); kpi(ctx,slide,'真实闭环','MQTT 事件验证通过',1200,575,300,C.purple);
      claim(ctx,slide,'当前项目已经具备期末汇报所需的研究问题、系统方案、实验过程、量化结果和真实运行证据。');
      break;
    }
    case 18: {
      title(ctx,slide,'后续工作：把工程成果整理成论文式表达','下一步重点是补足解释、录像演示和材料打包');
      bulletList(ctx,slide,[
        {text:'PPT：用本 deck 作为主线，录屏时按“问题—机制—实验—结论”讲。',color:C.cyan},
        {text:'视频：演示 Home Assistant 页面、真实 MQTT 验证脚本、实验结果目录。',color:C.green},
        {text:'论文/报告：重点写清楚评价指标、实验参数和消融结论。',color:C.orange},
        {text:'材料包：PPTX、MP4、代码、experiments/final_results、mqtt_validation 一起提交。',color:C.purple},
      ],110,250,1300,62,25);
      box(ctx,slide,130,570,1340,160,C.navy2,'#33445F',1); txt(ctx,slide,'最终汇报主张',165,600,260,34,{size:24,bold:true,color:'#8DE5FF'}); txt(ctx,slide,'本项目不是简单智能家居自动化，而是在边缘弱网络环境下，通过优先级、状态可信度和执行确认机制提高关键任务稳定性的自治 Agent 原型。',165,648,1220,70,{size:24,color:'#EEF4FF'});
      txt(ctx,slide,'谢谢',1320,790,180,44,{size:34,bold:true,color:C.ink,align:'right'});
      break;
    }
  }
  return slide;
}
