// His streak on the start and end screens (21). Only good news: a number appears only for a real
// streak (2+ days); one day is "a start", and a broken streak is "a new one starts today" -- never 0.
// Dependency-free: the page imports it, and `node --test tests/js/*.test.mjs` tests it as is.

// A compliment for the streak's size (the longer, the warmer).
const PRAISE = [
  [14, "שבועיים ויותר! זו כבר הרגל של אלופים"],
  [7, "שבוע שלם ברצף. כל הכבוד על ההתמדה"],
  [5, "אתה מתמיד, וזה מה שעושה את ההבדל"],
  [3, "יפה מאוד! ממשיכים ככה"],
  [2, "יומיים ברצף, התחלה מצוינת"],
];

export function streakLine(practice) {
  const days = practice?.days || 0;
  if (days >= 2) return { title: `${days} ימים ברצף`, praise: PRAISE.find(([min]) => days >= min)[1] };
  if (days === 1) return { title: "התחלת רצף", praise: practice.today ? "נמשיך מחר?" : "היום ממשיכים?" };
  return { title: "היום מתחילים רצף חדש", praise: "כל שיחה עוזרת" };
}
