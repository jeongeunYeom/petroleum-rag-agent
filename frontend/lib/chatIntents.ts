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
    case "verify": return "검증 중";
    case "waiting_for_user_input": return "추가 정보 필요";
    case "resume": return "계산을 계속하는 중";
    case "deliverables": return "산출물 작성 중";
    default: return "연구 진행 중";
  }
}
