// Флаг калькулятора v2. Пользователи видят v2, только если включён env CALC_V2=1 или задан ?v2=1
// (для тестирования). До фазы К3 дефолт — прежний простой калькулятор (нет регресса).

export function isCalcV2(v2Param: string | string[] | undefined): boolean {
  if (process.env.CALC_V2 === "1") return true;
  const v = Array.isArray(v2Param) ? v2Param[0] : v2Param;
  return v === "1";
}
