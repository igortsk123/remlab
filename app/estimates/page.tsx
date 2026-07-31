import { redirect } from "next/navigation";

// «Мои сметы» слились с «Моей лабораторией»: старый адрес ведёт туда (план e-save-button-clarity).
export default function EstimatesPage() {
  redirect("/lab");
}
