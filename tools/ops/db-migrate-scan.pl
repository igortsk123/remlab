#!/usr/bin/env perl
# РАЗБОР SQL МИГРАЦИИ для `db-migrate-safe.sh:sql_scan` (T-20261105-55): какие таблицы SQL меняет — их копию С ДАННЫМИ
# скрипт снимет до применения. Раньше разбор шёл одним grep по тексту и пропускал псевдоним («update products p set»),
# `with … update`, `merge into`, `truncate a, b`, `/* */`: таблица не попадала в копию, и при «все таблицы новые» копия
# была ТОЛЬКО СХЕМОЙ, без данных (поймано сухим прогоном T-53).
#
# Как разбирает: убирает комментарии (`--`, вложенные `/* */`) и содержимое строк ('…', E'…', $tag$…$tag$ — слова внутри
# строк не считаются SQL), режет на операторы по `;`, каждый оператор — по первому слову (белый список), плюс в КАЖДОМ
# операторе ищет все `update|delete|insert|merge` (CTE `with … as (update …)`, `explain analyze`) и требует для каждого
# разобрать целевую таблицу. Не разобрал — не гадает: строка «full <причина>», скрипт снимет копию ВСЕЙ БД с данными.
#
# Печатает: «t <таблица>» — SQL её пишет или меняет; «new <таблица>» — SQL её создаёт (create table);
#           «temp <таблица>» — временная (create temp table), в копию не идёт; «full <причина>» — не уверен.
#   perl tools/ops/db-migrate-scan.pl <файл.sql>
use strict;
use warnings;

my $file = shift // die "нужен файл .sql\n";
open my $fh, '<:raw', $file or die "нет файла $file\n";
my $src = do { local $/; <$fh> };
close $fh;

my (@full, %touch, %new, %temp);
my $ID = qr/(?:"(?:[^"]|"")+"|[a-z_][a-z0-9_\$]*)/;
my $QN = qr/$ID(?:\s*\.\s*$ID){0,2}/;

# --- 1. комментарии и строки → пробел / '' ; регистр — нижний вне "идентификаторов"
my $out = '';
pos($src) = 0;
my $len = length $src;
while (pos($src) < $len) {
  if ($src =~ /\G--[^\n]*/gc) { $out .= ' ' }
  elsif ($src =~ /\G\/\*/gc) {
    my $depth = 1;
    while ($depth) {
      if ($src =~ /\G\/\*/gc) { $depth++ }
      elsif ($src =~ /\G\*\//gc) { $depth-- }
      elsif ($src =~ /\G(?:[^\/*]++|.)/gcs) { }
      else { push @full, 'незакрытый комментарий /*'; last }
    }
    $out .= ' ';
  }
  elsif ($src =~ /\G(?<![A-Za-z0-9_\$])[eE]'(?:[^'\\]++|\\.|'')*+'/gcs) { $out .= "''" }
  elsif ($src =~ /\G'(?:[^']++|'')*+'/gc) { $out .= "''" }
  elsif ($src =~ /\G(?<![A-Za-z0-9_\$])(\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$)/gc) {
    my $tag = $1;
    if ($src =~ /\G.*?\Q$tag\E/gcs) { $out .= "''" } else { push @full, "незакрытая строка $tag"; last }
  }
  elsif ($src =~ /\G"(?:[^"]++|"")*+"/gc) { $out .= substr($src, $-[0], $+[0] - $-[0]) }
  elsif ($src =~ /\G['"]/gc) { push @full, 'незакрытая кавычка'; last }
  elsif ($src =~ /\G[^-\/'"\$eE]++/gc) { $out .= lc substr($src, $-[0], $+[0] - $-[0]) }
  else { $src =~ /\G./gcs; $out .= lc substr($src, $-[0], 1) }
}

# --- 2. имя таблицы: кавычки снять, «public.» снять; что не похоже на обычное имя — не гадаем
sub parts { my ($q) = @_; my @p = ($q =~ /("(?:[^"]|"")+"|[a-z_][a-z0-9_\$]*)/g); return @p }
sub norm {
  my @p = @_;
  for (@p) {
    if (s/^"(.*)"$/$1/s) { s/""/"/g; return undef unless /^[a-z_][a-z0-9_\$]*$/ }
  }
  return undef if @p < 1 || @p > 2;
  shift @p if @p == 2 && $p[0] eq 'public';
  return join '.', @p;
}
sub name_of { my ($q) = @_; my $n = norm(parts($q)); push @full, "имя «$q» не разобрать" unless defined $n; return $n }
sub touch { my $n = name_of($_[0]); $touch{$n} = 1 if defined $n; return $n }
sub touch_col {    # comment on column [схема.]таблица.колонка → таблица
  my @p = parts($_[0]);
  if (@p < 2) { push @full, "колонка «$_[0]» без таблицы"; return }
  pop @p;
  my $n = norm(@p);
  if (defined $n) { $touch{$n} = 1 } else { push @full, "имя «$_[0]» не разобрать" }
}
sub short { my $s = substr($_[0], 0, 50); return $s . (length $_[0] > 50 ? '…' : '') }
sub list_of {      # «a, only b *, c» → каждое имя; не имя — не гадаем
  my ($r, $what) = @_;
  for my $x (split /\s*,\s*/, $r) {
    if ($x =~ /^(?:only )?($QN)(?: ?\*)?$/) { touch($1) } else { push @full, "$what: «" . short($x) . "» не разобрать" }
  }
}

# --- 3. по операторам
for my $st (split /;/, $out) {
  $st =~ s/\s+/ /g;
  $st =~ s/^ //;
  $st =~ s/ $//;
  next if $st eq '';
  my ($head) = $st =~ /^([a-z_]+)/;
  $head //= '';

  # запись данных в любом месте оператора: CTE, explain analyze, insert … select. Слово без своей цели — только внутри
  # другого оператора: on conflict DO update, merge … THEN update/delete/insert, on update/delete cascade, for [no key] update
  while ($st =~ /\b(update|delete|insert|merge)\b/g) {
    my ($kw, $at) = ($1, $-[0]);
    my ($prev) = substr($st, 0, $at) =~ /([a-z_]+)\s*$/;
    next if ($prev // '') =~ /^(?:do|then|on|for|key)$/;
    my $rest = substr($st, $at);
    if ($kw eq 'update' && $rest =~ /^update (?:only )?($QN)(?: ?\*)?(?: (?:as )?$ID)? set\b/) { touch($1) }
    elsif ($kw eq 'delete' && $rest =~ /^delete from (?:only )?($QN)/) { touch($1) }
    elsif ($kw eq 'insert' && $rest =~ /^insert into ($QN)/) { touch($1) }
    elsif ($kw eq 'merge' && $rest =~ /^merge into (?:only )?($QN)/) { touch($1) }
    else { push @full, "запись «" . short($rest) . "» — цель не разобрать" }
  }

  if ($head =~ /^(?:select|with|values|table|explain|insert|update|delete|merge)$/) {
    # select … into НОВАЯ_ТАБЛИЦА создаёт таблицу — редкость, не разбираем
    my $into = () = $st =~ /\binto\b/g;
    my $dml_into = () = $st =~ /\b(?:insert|merge) into\b/g;
    push @full, "select … into «" . short($st) . "»" if $into > $dml_into;
  }
  elsif ($head eq 'copy') {
    if ($st =~ /^copy ($QN)(?: ?\([^)]*\))? from\b/) { touch($1) }
    elsif ($st !~ /^copy (?:$QN(?: ?\([^)]*\))?|\(.*\)) to\b/) { push @full, "copy «" . short($st) . "»" }
  }
  elsif ($head eq 'truncate') {
    (my $r = $st) =~ s/^truncate (?:table )?//;
    push @full, 'truncate … cascade чистит и чужие таблицы' if $r =~ /\bcascade$/;
    $r =~ s/ (?:restart|continue) identity\b//;
    $r =~ s/ (?:cascade|restrict)$//;
    list_of($r, 'truncate');
  }
  elsif ($head eq 'create') {
    if ($st =~ /^create (?:(?:(?:global |local )?(temp|temporary) )|unlogged )?table (?:if not exists )?($QN)/) {
      my ($tmp, $q) = ($1, $2);
      my $n = name_of($q);
      if (defined $n) { if ($tmp) { $temp{$n} = 1 } else { $new{$n} = 1; $touch{$n} = 1 } }
      touch($1) if $st =~ /\bpartition of ($QN)/;    # секция чужой таблицы меняет и её
    }
    elsif ($st =~ /^create (?:unique )?index (?:if not exists )?(?:$ID )?on (?:only )?($QN)/) { touch($1) }
    else { push @full, "create «" . short($st) . "» — не таблица и не индекс" }
  }
  elsif ($head eq 'alter') {
    if ($st =~ /^alter table (?:if exists )?(?:only )?($QN)/) {
      touch($1);
      push @full, "переименование/перенос таблицы «" . short($st) . "» — копия по имени его не откатит"
        if $st =~ /\b(?:rename to|set schema)\b/;
    }
    else { push @full, "alter «" . short($st) . "» — не таблица" }
  }
  elsif ($head eq 'drop') {
    if ($st =~ /^drop table (?:if exists )?(.+)$/) {
      my $r = $1;
      push @full, 'drop table … cascade роняет и зависимые объекты' if $r =~ /\bcascade$/;
      $r =~ s/ (?:cascade|restrict)$//;
      list_of($r, 'drop table');
    }
    else { push @full, "drop «" . short($st) . "» — не таблица" }
  }
  elsif ($head eq 'comment') {
    if ($st =~ /^comment on table ($QN)/) { touch($1) }
    elsif ($st =~ /^comment on column ($QN)/) { touch_col($1) }
    else { push @full, "comment «" . short($st) . "» — не таблица и не колонка" }
  }
  elsif ($head eq 'set') {
    push @full, "«" . short($st) . "» меняет, где искать таблицы" if $st =~ /^set (?:local |session )?(?:search_path|schema|role|session authorization)\b/;
  }
  elsif ($head =~ /^(?:reset|show|analyze|analyse|lock)$/) { }
  else { push @full, "оператор «" . short($st) . "» не знаем" }
}

my %seen;
@full = grep { !$seen{$_}++ } @full;
if (@full) {
  my $why = join '; ', @full[0 .. ($#full < 2 ? $#full : 2)];
  $why .= " (и ещё " . (@full - 3) . ")" if @full > 3;
  print "full сканер не уверен: $why\n";
}
print "temp $_\n" for sort keys %temp;
print "new $_\n" for sort grep { !$temp{$_} } keys %new;
print "t $_\n" for sort grep { !$temp{$_} } keys %touch;
