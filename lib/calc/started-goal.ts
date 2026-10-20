import { trackGoal } from "@/lib/metrika";

// Цель Метрики «расчёт начат» (581529922 `10_calc_started`, воронка сметы) для калькуляторов v2.
// В v1 её слал CalcForm по кнопке «Посчитать» (onSubmit). В v2 кнопки нет — итог считается на лету, поэтому
// «начал расчёт» = первая ПРАВКА пользователя, после которой площадь > 0. Одна цель на расчёт: повтор — только
// после «новый расчёт» (reset). Открытие страницы и подгрузка черновика из localStorage — не правка, цель не шлют.
// Отправка — через trackGoal: правило metrikaAllowed() и согласие в английском режиме — как у остальных целей.
export function calcStartedGoal(send: () => void = () => trackGoal("calc_started")) {
  let sent = false;
  return {
    /** Пользователь изменил расчёт; hasArea — площадь итога > 0. */
    edited(hasArea: boolean): void {
      if (hasArea && !sent) {
        sent = true;
        send();
      }
    },
    /** «Новый расчёт» — следующая площадь снова считается началом. */
    reset(): void {
      sent = false;
    },
  };
}
