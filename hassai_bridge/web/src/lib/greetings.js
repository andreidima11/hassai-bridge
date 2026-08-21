/** Curated chat greetings — local pool, no LLM. Context: period, holiday, weather. */

function pad(n) {
  return String(n).padStart(2, "0");
}

function ymd(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function addDays(date, days) {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
  return next;
}

/** Orthodox Easter (Gregorian) via Meeus Julian + 13-day offset (valid 1900–2099). */
export function orthodoxEaster(year) {
  const a = year % 4;
  const b = year % 7;
  const c = year % 19;
  const d = (19 * c + 15) % 30;
  const e = (2 * a + 4 * b - d + 34) % 7;
  const month = Math.floor((d + e + 114) / 31);
  const day = ((d + e + 114) % 31) + 1;
  return addDays(new Date(year, month - 1, day), 13);
}

/** Western / Gregorian Easter (Anonymous Gregorian algorithm). */
export function westernEaster(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(year, month - 1, day);
}

export function dayPeriod(date = new Date()) {
  const h = date.getHours();
  if (h >= 5 && h < 12) return "morning";
  if (h >= 12 && h < 18) return "afternoon";
  if (h >= 18 && h < 23) return "evening";
  return "night";
}

function holidayId(lang, date = new Date()) {
  const key = ymd(date);
  const y = date.getFullYear();
  const md = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const oe = orthodoxEaster(y);
  const we = westernEaster(y);
  const oeKey = ymd(oe);
  const oeMon = ymd(addDays(oe, 1));
  const weKey = ymd(we);
  const pentecost = ymd(addDays(oe, 49));
  const martisor = `${y}-03-01`;
  const women = `${y}-03-08`;
  const labor = `${y}-05-01`;
  const national = `${y}-12-01`;
  const xmas = `${y}-12-25`;
  const xmas2 = `${y}-12-26`;
  const nye = `${y}-12-31`;
  const ny1 = `${y}-01-01`;
  const ny2 = `${y}-01-02`;
  const valentine = `${y}-02-14`;
  const halloween = `${y}-10-31`;

  if (lang === "ro") {
    if (key === oeKey || key === oeMon) return "easter";
    if (key === pentecost) return "pentecost";
    if (key === martisor) return "martisor";
    if (key === women) return "womens_day";
    if (key === national) return "national_day";
    if (key === xmas || key === xmas2) return "christmas";
    if (key === nye) return "new_year_eve";
    if (key === ny1 || key === ny2) return "new_year";
    if (key === labor) return "labor_day";
    if (key === valentine) return "valentine";
    if (md === "08-15") return "assumption";
    if (md === "11-30") return "st_andrew";
    if (md === "01-24") return "union_day";
  } else {
    if (key === weKey || key === ymd(addDays(we, 1))) return "easter";
    if (key === xmas || key === xmas2) return "christmas";
    if (key === nye) return "new_year_eve";
    if (key === ny1) return "new_year";
    if (key === valentine) return "valentine";
    if (key === halloween) return "halloween";
    if (key === labor) return "labor_day";
  }
  return "";
}

function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function pickIndex(seed, length) {
  if (length <= 1) return 0;
  return hashSeed(seed) % length;
}

/**
 * Greeting catalog. Tags: general | morning | afternoon | evening | night |
 * rainy | snowy | sunny | clear_night | stormy | foggy | cloudy | windy | hot | cold |
 * easter | christmas | new_year | new_year_eve | valentine | halloween |
 * national_day | labor_day | martisor | womens_day | pentecost | assumption | st_andrew | union_day
 */
const GREETINGS = [
  // —— general ——
  {
    tags: ["general"],
    title: { en: "Hey — what's up?", ro: "Hei — ce mai faci?" },
    hint: { en: "Ask anything. Home stuff, ideas, or just chat.", ro: "Întreabă orice. Casă, idei, sau doar o vorbă." },
  },
  {
    tags: ["general"],
    title: { en: "I'm here.", ro: "Sunt pe fază." },
    hint: { en: "Say what you need — short or long, either works.", ro: "Spune ce ai nevoie — scurt sau pe larg, ambele merg." },
  },
  {
    tags: ["general"],
    title: { en: "Ready when you are.", ro: "Gata când ești și tu." },
    hint: { en: "A quick question or a bigger plan — start wherever.", ro: "O întrebare scurtă sau un plan mai mare — începe de unde vrei." },
  },
  {
    tags: ["general"],
    title: { en: "What are we doing?", ro: "Ce facem?" },
    hint: { en: "Devices, dashboards, recipes, random thoughts — go ahead.", ro: "Dispozitive, dashboard-uri, rețete, gânduri random — hai." },
  },
  {
    tags: ["general"],
    title: { en: "Got a minute?", ro: "Ai un minut?" },
    hint: { en: "I can help with chores, questions, or whatever's on your mind.", ro: "Te pot ajuta cu treburi, întrebări, sau orice ai pe creier." },
  },
  {
    tags: ["general"],
    title: { en: "Fire away.", ro: "Trage." },
    hint: { en: "No need to be formal. Just type.", ro: "Nu trebuie să fii formal. Scrie și gata." },
  },
  {
    tags: ["general"],
    title: { en: "What's cooking?", ro: "Ce se mai aude?" },
    hint: { en: "Smart home or not — I'm listening.", ro: "Smart home sau nu — te ascult." },
  },
  {
    tags: ["general"],
    title: { en: "Let's start.", ro: "Hai să începem." },
    hint: { en: "One sentence is enough to get going.", ro: "O singură propoziție e destul ca să pornim." },
  },

  // —— time of day ——
  {
    tags: ["morning"],
    title: { en: "Good morning.", ro: "Bună dimineața." },
    hint: { en: "Coffee first, then whatever you need.", ro: "Mai întâi cafeaua, apoi ce ai nevoie." },
  },
  {
    tags: ["morning"],
    title: { en: "Morning — fresh start?", ro: "Dimineață — start fresh?" },
    hint: { en: "Want a quick rundown, or jump straight in?", ro: "Vrei un rezumat rapid, sau intrăm direct?" },
  },
  {
    tags: ["afternoon"],
    title: { en: "Good afternoon.", ro: "Bună ziua." },
    hint: { en: "Midday energy — use it for something useful.", ro: "Energie de mijloc de zi — hai s-o folosim la ceva util." },
  },
  {
    tags: ["afternoon"],
    title: { en: "Still going strong?", ro: "Încă pe drum?" },
    hint: { en: "Ask for a hand with whatever's next on the list.", ro: "Cere o mână de ajutor pentru ce urmează pe listă." },
  },
  {
    tags: ["evening"],
    title: { en: "Good evening.", ro: "Bună seara." },
    hint: { en: "Wind down mode — or one last task before you stop.", ro: "Mod de relaxare — sau o ultimă treabă înainte să te oprești." },
  },
  {
    tags: ["evening"],
    title: { en: "Evening check-in.", ro: "Check-in de seară." },
    hint: { en: "Lights, scenes, or just a quiet question.", ro: "Lumini, scene, sau doar o întrebare liniștită." },
  },
  {
    tags: ["night"],
    title: { en: "Still up?", ro: "Încă treaz?" },
    hint: { en: "Keep it light — or tell me what's keeping you awake.", ro: "Ține-o ușor — sau spune-mi ce te ține treaz." },
  },
  {
    tags: ["night"],
    title: { en: "Late shift.", ro: "Tură de noapte." },
    hint: { en: "I'm around if you need something quiet and quick.", ro: "Sunt pe-aproape dacă ai nevoie de ceva liniștit și rapid." },
  },

  // —— weather ——
  {
    tags: ["rainy"],
    title: { en: "Rainy out there.", ro: "Plouă afară." },
    hint: { en: "Perfect indoor weather — what should we tackle?", ro: "Vreme perfectă de stat în casă — ce atacăm?" },
  },
  {
    tags: ["rainy"],
    title: { en: "Wet day vibes.", ro: "Zi de ploaie." },
    hint: { en: "Stay dry. Ask me anything from the couch.", ro: "Stai uscat. Întreabă-mă orice de pe canapea." },
  },
  {
    tags: ["snowy"],
    title: { en: "It's snowing.", ro: "Ninge." },
    hint: { en: "Cozy mode on — want help with something warm?", ro: "Mod cozy activat — vrei ajutor cu ceva călduros?" },
  },
  {
    tags: ["sunny"],
    title: { en: "Nice and sunny.", ro: "Frumos și însorit." },
    hint: { en: "Good day to get things done — or just enjoy it.", ro: "Zi bună de făcut treabă — sau doar de savurat." },
  },
  {
    tags: ["clear_night"],
    title: { en: "Clear night sky.", ro: "Cer senin noaptea." },
    hint: { en: "Quiet outside — ask me anything before you turn in.", ro: "Liniște afară — întreabă-mă orice înainte să te culci." },
  },
  {
    tags: ["stormy"],
    title: { en: "Stormy weather.", ro: "Vreme de furtună." },
    hint: { en: "Stay safe inside. I can help while it passes.", ro: "Stai în siguranță în casă. Te ajut până trece." },
  },
  {
    tags: ["foggy"],
    title: { en: "Foggy outside.", ro: "Ceață afară." },
    hint: { en: "Low visibility day — let's keep plans simple.", ro: "Zi cu vizibilitate redusă — hai să ținem planurile simple." },
  },
  {
    tags: ["cloudy"],
    title: { en: "Cloudy skies.", ro: "Cer înnorat." },
    hint: { en: "Soft light day — good for focus or a slow chat.", ro: "Lumină blândă — bună de focus sau de vorbit pe îndelete." },
  },
  {
    tags: ["windy"],
    title: { en: "It's windy.", ro: "E vânt afară." },
    hint: { en: "Hold onto your hat — and tell me what you need.", ro: "Ține-ți pălăria — și spune-mi de ce ai nevoie." },
  },
  {
    tags: ["hot"],
    title: { en: "It's warm out.", ro: "E cald afară." },
    hint: { en: "Stay cool — AC, fans, or a cold drink plan?", ro: "Stai răcoros — AC, ventilatoare, sau un plan cu ceva rece?" },
  },
  {
    tags: ["cold"],
    title: { en: "Chilly today.", ro: "Răcoare azi." },
    hint: { en: "Heat, blankets, soup — or just a quick question.", ro: "Căldură, pături, ciorbă — sau doar o întrebare scurtă." },
  },

  // —— holidays ——
  {
    tags: ["easter"],
    title: { en: "Happy Easter!", ro: "Paște fericit!" },
    hint: { en: "Hope it's a bright one. What can I help with today?", ro: "Să fie luminos. Cu ce te pot ajuta azi?" },
  },
  {
    tags: ["christmas"],
    title: { en: "Merry Christmas!", ro: "Crăciun fericit!" },
    hint: { en: "Warm wishes — and I'm here if you need anything.", ro: "Urări calde — și sunt aici dacă ai nevoie de ceva." },
  },
  {
    tags: ["new_year"],
    title: { en: "Happy New Year!", ro: "La mulți ani!" },
    hint: { en: "New year, fresh page. What shall we start with?", ro: "An nou, pagină goală. Cu ce începem?" },
  },
  {
    tags: ["new_year_eve"],
    title: { en: "New Year's Eve.", ro: "Ajun de Anul Nou." },
    hint: { en: "Almost there — need a hand before midnight?", ro: "Aproape — ai nevoie de o mână înainte de miezul nopții?" },
  },
  {
    tags: ["valentine"],
    title: { en: "Happy Valentine's.", ro: "La mulți ani de Sfântul Valentin." },
    hint: { en: "Something sweet, something useful — your call.", ro: "Ceva dulce, ceva util — tu alegi." },
  },
  {
    tags: ["halloween"],
    title: { en: "Happy Halloween.", ro: "Halloween fericit." },
    hint: { en: "Spooky or cozy — I'm game either way.", ro: "Înfricoșător sau cozy — merg pe ambele." },
  },
  {
    tags: ["national_day"],
    title: { en: "Happy National Day!", ro: "La mulți ani, România!" },
    hint: { en: "A day to celebrate — and I'm still here if you need me.", ro: "O zi de sărbătoare — și tot sunt aici dacă ai nevoie." },
  },
  {
    tags: ["labor_day"],
    title: { en: "Happy Labor Day.", ro: "1 Mai fericit!" },
    hint: { en: "Rest if you can — or ask me for a quick favor.", ro: "Odihnește-te dacă poți — sau cere-mi o mică favoare." },
  },
  {
    tags: ["martisor"],
    title: { en: "Happy Mărțișor!", ro: "Mărțișor fericit!" },
    hint: { en: "Spring is near — what should we start today?", ro: "Primăvara e aproape — ce începem azi?" },
  },
  {
    tags: ["womens_day"],
    title: { en: "Happy Women's Day.", ro: "La mulți ani de 8 Martie!" },
    hint: { en: "A kind day — tell me how I can help.", ro: "O zi cu gânduri bune — spune-mi cum te pot ajuta." },
  },
  {
    tags: ["pentecost"],
    title: { en: "Happy Pentecost.", ro: "Rusalii fericite!" },
    hint: { en: "A quiet holiday — I'm here when you need me.", ro: "O sărbătoare liniștită — sunt aici când ai nevoie." },
  },
  {
    tags: ["assumption"],
    title: { en: "Happy holiday.", ro: "Sfântă Maria Mare!" },
    hint: { en: "Hope you're having a peaceful day.", ro: "Să ai o zi liniștită." },
  },
  {
    tags: ["st_andrew"],
    title: { en: "Happy St. Andrew's Day.", ro: "La mulți ani de Sfântul Andrei!" },
    hint: { en: "Romania's patron day — what can I do for you?", ro: "Ziua patronului României — cu ce te pot ajuta?" },
  },
  {
    tags: ["union_day"],
    title: { en: "Happy Union Day.", ro: "La mulți ani de Unirea Principatelor!" },
    hint: { en: "A historic day — ask me anything when you're ready.", ro: "O zi cu istorie — întreabă-mă orice când ești gata." },
  },
];

function weatherTags(atmosphere, period = "") {
  const tags = [];
  let weather = String(atmosphere?.weather || "").toLowerCase();
  // Never use daytime "sunny" copy after dark (HA clear-night used to map to sunny).
  if (weather === "sunny" && period === "night") weather = "clear_night";
  if (weather) tags.push(weather);
  const temp = atmosphere?.temp;
  const unit = String(atmosphere?.temp_unit || "°C").toUpperCase();
  if (typeof temp === "number" && Number.isFinite(temp)) {
    const celsius = unit.includes("F") ? ((temp - 32) * 5) / 9 : temp;
    if (celsius >= 28 && period !== "night") tags.push("hot");
    if (celsius <= 3) tags.push("cold");
  }
  return tags;
}

function scoreGreeting(entry, activeTags) {
  let score = 0;
  for (const tag of entry.tags) {
    if (!activeTags.has(tag)) continue;
    if (tag === "general") score += 1;
    else if (["morning", "afternoon", "evening", "night"].includes(tag)) score += 4;
    else if (
      ["rainy", "snowy", "sunny", "clear_night", "stormy", "foggy", "cloudy", "windy", "hot", "cold"].includes(tag)
    ) {
      score += 8;
    } else score += 20; // holidays win
  }
  return score;
}

/**
 * Pick a contextual greeting. Stable for the same day + period + weather bucket
 * so re-renders don't flicker; changes across visits/times.
 */
export function pickGreeting(lang = "en", atmosphere = {}, date = new Date(), nonce = 0) {
  const period = dayPeriod(date);
  const holiday = holidayId(lang, date);
  const wx = weatherTags(atmosphere, period);
  const active = new Set(["general", period, ...wx]);
  if (holiday) active.add(holiday);

  let bestScore = -1;
  const pool = [];
  for (const entry of GREETINGS) {
    const score = scoreGreeting(entry, active);
    if (score <= 0) continue;
    if (score > bestScore) {
      bestScore = score;
      pool.length = 0;
      pool.push(entry);
    } else if (score === bestScore) {
      pool.push(entry);
    }
  }
  const fallback = GREETINGS.filter((g) => g.tags.includes("general"));
  const use = pool.length ? pool : fallback;
  const seed = [
    ymd(date),
    period,
    holiday || "-",
    wx.join(",") || "-",
    lang,
    String(nonce || 0),
  ].join("|");
  const chosen = use[pickIndex(seed, use.length)] || fallback[0];
  return {
    title: chosen.title[lang] || chosen.title.en,
    hint: chosen.hint[lang] || chosen.hint.en,
    period,
    holiday: holiday || null,
    weather: atmosphere?.weather || null,
  };
}
