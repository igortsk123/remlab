# merge-settings — ps1-пара tools/merge-settings.py (для apply.ps1 на Windows).
# Parity-контракт: tests/merge-cases/*.json — обе реализации обязаны давать одинаковый результат.
# Меняешь логику здесь — поменяй в python-паре и добавь кейс в merge-cases.
#
# Контракт:
#   - permissions.defaultMode берётся из пресета;
#   - permissions.allow/ask — СМЕНА РЕЖИМА, а не накопление:
#       result = [записи existing, которых нет в kit-managed] ++ [записи пресета]  (без дублей).
#     kit-managed — объединение allow/ask/deny всех пресетов кита, найденных рядом с
#     применяемым (файлы default|important|autopilot|plan-first.json в его каталоге).
#     Смысл: записи, принадлежащие ДРУГОМУ режиму, при переключении уходят (иначе autopilot
#     после important навсегда остаётся с его ask-списком — а ask сильнее allow, и режим
#     фактически не меняется). Пользовательские записи ни в один пресет не входят → выживают.
#     Соседних пресетов нет (напр. в тестах) → kit-managed пуст → прежнее поведение-объединение.
#   - permissions.deny — ТОЛЬКО объединение, вычитания НЕТ. Пресеты кита `deny` не задают
#     вообще, значит любая запись в deny — авторская. Вычитание сняло бы жёсткий блок: напр.
#     `Bash(rm -rf /)` лежит в `ask` пресетов, т.е. является kit-managed, и был бы вычтен из
#     авторского deny — хардблок молча превратился бы в вопрос. Недопустимо (поймано на sib).
#   - hooks: если в existing нет своего блока hooks — переносится из пресета целиком;
#     свои hooks пользователя не трогаются (глубокого merge нет);
#   - остальные ключи existing не трогаются;
#   - если результат не отличается — печатается __NOCHANGE__.
#
# Usage: merge-settings.ps1 -PresetPath <preset.json> -ExistingPath <existing.json>
param(
  [Parameter(Mandatory = $true)][string]$PresetPath,
  [Parameter(Mandatory = $true)][string]$ExistingPath
)
$ErrorActionPreference = "Stop"

$preset = Get-Content $PresetPath -Raw | ConvertFrom-Json
$origText = Get-Content $ExistingPath -Raw
$existing = $origText | ConvertFrom-Json

# kit-managed: объединение allow/ask/deny всех пресетов кита рядом с применяемым.
$managed = New-Object 'System.Collections.Generic.HashSet[string]'
$presetDir = Split-Path -Parent (Resolve-Path $PresetPath)
foreach ($name in 'default', 'important', 'autopilot', 'plan-first') {
  $p = Join-Path $presetDir "$name.json"
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
  try { $other = Get-Content $p -Raw | ConvertFrom-Json } catch { continue }
  if (-not $other.permissions) { continue }
  foreach ($k in 'allow', 'ask', 'deny') {
    if ($other.permissions.PSObject.Properties.Name -contains $k -and $other.permissions.$k) {
      foreach ($e in @($other.permissions.$k)) { [void]$managed.Add([string]$e) }
    }
  }
}

if (-not $existing.permissions) {
  $existing | Add-Member -NotePropertyName permissions -NotePropertyValue ([pscustomobject]@{}) -Force
}
$perm = $existing.permissions
if ($preset.permissions.PSObject.Properties.Name -contains 'defaultMode') {
  $perm | Add-Member -NotePropertyName defaultMode -NotePropertyValue $preset.permissions.defaultMode -Force
}
foreach ($k in 'allow', 'ask', 'deny') {
  $cur = @(); if ($perm.PSObject.Properties.Name -contains $k -and $perm.$k) { $cur = @($perm.$k) }
  # deny — авторский жёсткий блок, вычитать нельзя (см. контракт в шапке).
  if ($k -ne 'deny') { $cur = @($cur | Where-Object { -not $managed.Contains([string]$_) }) }
  $add = @(); if ($preset.permissions.PSObject.Properties.Name -contains $k -and $preset.permissions.$k) { $add = @($preset.permissions.$k) }
  $union = @($cur + $add | Select-Object -Unique)
  $perm | Add-Member -NotePropertyName $k -NotePropertyValue $union -Force
}
if (($preset.PSObject.Properties.Name -contains 'hooks') -and -not ($existing.PSObject.Properties.Name -contains 'hooks')) {
  $existing | Add-Member -NotePropertyName hooks -NotePropertyValue $preset.hooks -Force
}

$mergedJson = $existing | ConvertTo-Json -Depth 20
$origNorm = ($origText | ConvertFrom-Json) | ConvertTo-Json -Depth 20
if ($origNorm -eq $mergedJson) {
  Write-Output "__NOCHANGE__"
}
else {
  Write-Output $mergedJson
}
