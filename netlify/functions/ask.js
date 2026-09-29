const research = require("../../site/demo-data/research/latest.json");

function json(statusCode, payload) {
  return { statusCode, headers: { "content-type": "application/json; charset=utf-8" }, body: JSON.stringify(payload) };
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return json(405, { error: "POST only" });
  if (Buffer.byteLength(event.body || "", "utf8") > 8192) return json(413, { error: "Request too large" });
  let question;
  try {
    question = JSON.parse(event.body || "{}").question;
  } catch {
    return json(400, { error: "Invalid JSON body" });
  }
  if (typeof question !== "string" || !question.trim() || question.length > 2000) {
    return json(400, { error: "question must contain 1 to 2000 characters" });
  }
  return json(200, {
    answer: `합성 데이터 데모입니다. 예제 이슈: ${research.issues.map((item) => item.title).join(", ")}. 실제 시장 정보가 아닙니다.`,
    mode: "local", researchDate: research.date,
  });
};
