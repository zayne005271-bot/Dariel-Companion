// extensions/Dariel-Companion/index.js
const fs = require('fs');
const path = require('path');

export function init(context) {
    const { registerFunctionTool } = context.SillyTavern;

    // ==================== 记忆系统数据文件 ====================
    const memoryDir = path.join(__dirname, 'memory');
    const memoryFile = path.join(memoryDir, 'user_memory.json');
    const emotionLogFile = path.join(memoryDir, 'emotion_log.json');

    if (!fs.existsSync(memoryDir)) fs.mkdirSync(memoryDir, { recursive: true });
    if (!fs.existsSync(memoryFile)) fs.writeFileSync(memoryFile, '{}');
    if (!fs.existsSync(emotionLogFile)) fs.writeFileSync(emotionLogFile, '[]');

    // ==================== 辅助函数 ====================
    function readMemory() {
        try { return JSON.parse(fs.readFileSync(memoryFile, 'utf8')); } catch { return {}; }
    }
    function writeMemory(data) {
        fs.writeFileSync(memoryFile, JSON.stringify(data, null, 2));
    }
    function readEmotionLog() {
        try { return JSON.parse(fs.readFileSync(emotionLogFile, 'utf8')); } catch { return []; }
    }
    function writeEmotionLog(data) {
        fs.writeFileSync(emotionLogFile, JSON.stringify(data, null, 2));
    }

    // 发送系统消息到当前聊天
    function sendSystemPrompt(text) {
        if (context.sendSystemMessage) {
            context.sendSystemMessage(text, { role: 'system' });
        }
    }

    // ==================== 1. 工具调用基础 ====================
    // 天气查询（模拟，可替换真实API）
    registerFunctionTool({
        name: 'get_weather',
        description: '查询指定城市的实时天气',
        parameters: {
            type: 'object',
            properties: {
                city: { type: 'string', description: '城市名称，如南京、北京' }
            },
            required: ['city']
        },
        async execute(args) {
            // 模拟天气数据，实际使用时替换为真实API调用
            const weatherDB = {
                '南京': '多云，12°C，北风2级，今天有小雨',
                '北京': '晴，8°C，西北风3级',
                '上海': '阴，15°C，东风1级',
                '广州': '多云，22°C，南风2级',
                '成都': '小雨，10°C，北风1级'
            };
            const city = args.city || '南京';
            const result = weatherDB[city] || `暂时查不到${city}的天气数据`;
            // 记录到记忆
            const mem = readMemory();
            mem.lastWeatherQuery = { city, result, time: new Date().toISOString() };
            writeMemory(mem);
            return `${city}当前天气：${result}`;
        }
    });

    // 计算器
    registerFunctionTool({
        name: 'calculator',
        description: '执行基础数学计算',
        parameters: {
            type: 'object',
            properties: {
                expression: { type: 'string', description: '数学表达式，如2+3*4' }
            },
            required: ['expression']
        },
        async execute(args) {
            try {
                const result = Function('"use strict"; return (' + args.expression + ')')();
                return `计算结果：${args.expression} = ${result}`;
            } catch {
                return '无法计算该表达式，请检查输入。';
            }
        }
    });

    // ==================== 2. 主动消息与定时任务 ====================
    let saidGoodMorningToday = false;
    let saidGoodNightToday = false;
    let lastUserMessageTime = Date.now();
    let silenceReminderSent = false;

    // 监听用户消息以更新活跃时间
    const originalOnMessage = context.onMessageReceived;
    if (typeof originalOnMessage === 'function') {
        context.onMessageReceived = function (...args) {
            lastUserMessageTime = Date.now();
            silenceReminderSent = false;
            return originalOnMessage.apply(this, args);
        };
    }

    setInterval(() => {
        const now = new Date();
        const hour = now.getHours();
        const minute = now.getMinutes();

        // 早安：每天 8:00-8:10
        if (hour === 8 && minute < 10 && !saidGoodMorningToday) {
            saidGoodMorningToday = true;
            saidGoodNightToday = false;
            const mem = readMemory();
            const nickname = mem.nickname || 'Tifar';
            sendSystemPrompt(
                `现在是早上8点。请主动向 ${nickname} 道早安。话语温柔克制，提醒她注意保暖、先喝温水再吃东西、别空腹喝咖啡。限30字以内。`
            );
        }

        // 晚安：每天 23:00-23:10
        if (hour === 23 && minute < 10 && !saidGoodNightToday) {
            saidGoodNightToday = true;
            sendSystemPrompt(
                '现在是晚上11点。请提醒 Tifar 早点休息，语气温柔但不要唠叨。如果今天她看起来疲惫，多说一句安抚的话。'
            );
        }

        // 每日0点重置
        if (hour === 0 && minute === 0) {
            saidGoodMorningToday =
