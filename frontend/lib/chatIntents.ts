export function wantsFigureReview(message: string): boolean {
  return /(?:figure|figures|그림|도판|추출된\s*그림)/i.test(message) &&
    /(?:보여|확인|열어|검토|review|show|open|view)/i.test(message);
}

export function goalStageLabel(stage: string): string {
  switch (stage) {
    case "retrieve": return "자료 검색 중";
    case "calculate": return "계산 중";
    case "simulate": return "시뮬레이션 중";
    case "analyze": return "결과 분석 중";
    case "verify": return "결과 검증 중";
    case "synthesize": return "답변 작성 중";
    case "waiting_for_user_input": return "추가 정보 필요";
    case "resume": return "계산을 계속하는 중";
    case "deliverables": return "산출물 작성 중";
    default: return "요청을 분석하고 있습니다";
  }
}

export function boundedChatContext(messages: { role: "user" | "assistant"; content: string }[]) {
  const selected: { role: "user" | "assistant"; content: string }[] = [];
  let remaining = 2400;
  for (const message of messages.slice(-6).reverse()) {
    const content = message.content.trim();
    if (!content || content.length > 1000 || content.length > remaining) continue;
    selected.unshift({ role: message.role, content });
    remaining -= content.length;
  }
  return selected;
}

export function pendingGoalRun<T extends { role: string; goalRun?: { run_id: string; run_status: string } }>(messages: T[]) {
  const latest = [...messages].reverse().find((item) => item.role === "assistant" && item.goalRun)?.goalRun;
  return latest?.run_status === "waiting_for_user_input" ? latest : null;
}
