
# ExtendedSQL Syntax

This document contains information about writing ESQL queries. I will be providing examples as if I was writing a queries for the 'sales' table. The sales table can be found [here](/public/data/sales.csv) or at `/public/data/sales.csv`.

This document is prose. The token sets it describes — the six keywords, the five aggregate functions, the comparison operators, and the semi-join predicate — are defined once in [`src/esql/parser/util.py`](../../src/esql/parser/util.py) as `KEYWORDS`, `AGGREGATE_FUNCTIONS`, `CONDITIONAL_OPERATORS` and `SEMI_JOIN_OPERATOR`, re-exported from `esql`. Read those if you need the authoritative list.

The per-clause rules this document explains in prose are also available machine-readable as `esql.GRAMMAR` (see [`src/esql/grammar.py`](../../src/esql/grammar.py)): which slot kinds each clause accepts, which operators are legal in it, which column types each operator applies to, and what it requires. Anything generating a completion menu or a reference table should read that rather than re-deriving it from this page.

## Table of Contents
- [Structure](#structure)
  - [Text values](#text-values)
- [SELECT](#select)
  - [Counting](#counting)
- [OVER](#over)
- [WHERE](#where)
  - [Which operators apply to which columns](#which-operators-apply-to-which-columns)
  - [CONTAINS](#contains)
  - [HAS](#has)
- [SUCH THAT](#such-that)
  - [Entry values](#entry-values)
- [HAVING](#having)
- [ORDER BY](#order-by)
  - [The number shorthand](#the-number-shorthand)


## Structure

The basic structure of ExtendedSQL is defined below.

```sh
SELECT [grouping attrubutes and aggregates]
OVER [groups]
WHERE [global conditions]
SUCH THAT [group1 conditions],
          [group2 conditions], 
          ...
HAVING [aggregate conditions]
ORDER BY [variable order]
```

<!-- grammar:keywords -->
The query language has 6 keywords: `SELECT`, `OVER`, `WHERE`, `SUCH THAT`, `HAVING`, and `ORDER BY`. The follpowing sections explore the the syntax and use cases of each keyword. ESQL queries do not contain a FROM clause like in SQL since a datatable must be passed in through the DataFrame accessor or through the API. Queries do not require all of the keywords, but variable projection (in the [SELECT](#select) clause) must be performed for the query to produce an output.

### Case

ESQL is not case sensitive. Keywords, operators, column names, group names and aggregate functions can be written in any case, so `SELECT Cust, QUANT.SUM` and `select cust, quant.sum` are the same query. A column name is matched against the DataFrame's columns without regard to case, so a frame whose columns are `Cust` and `Quant` is queryable however you spell them.

What is case sensitive is a **text value**, because its contents are data rather than a spelling: `WHERE prod = 'Ham'` and `WHERE prod = 'HAM'` are different filters. The exception is [`CONTAINS`](#where), which is deliberately case insensitive.

A result is labelled with the *canonical* spelling rather than the query's, so the same query returns the same column names whatever case it was typed in: a column as the DataFrame spells it, a group as the [OVER](#over) clause declared it, and an aggregate function in lower case. `SELECT CUST, QUANT.SUM` over a frame with a `Cust` column returns columns `Cust` and `Quant.sum`.


### Text values

<!-- grammar:text-delimiters -->
A text value is written between a matched pair of `'` or `"`. Either delimiter holds the other as ordinary text, so a value containing an apostrophe is usually easiest to write in double quotes:

```sh
WHERE song = "(I'm A) Road Runner"
```

A delimiter holds *itself* by being written twice, the way SQL escapes a quote. This is the form that covers a value containing both kinds:

```sh
WHERE song = '(I''m A) Road Runner'
WHERE title = 'He said "it''s fine"'
```

Only the delimiter *in use* is doubled. Inside a double-quoted value an apostrophe is already ordinary text, so `"It''s"` is not an escape at all and denotes two apostrophes:

| written | denotes |
|---|---|
| `'It''s'` | `It's` |
| `"It's"` | `It's` |
| `"It''s"` | `It''s` |

Case and spacing inside a text value are data and are carried through exactly as written, so `'Dark  Star'` looks for two spaces and does not match `Dark Star`. This is also why a keyword inside a value is only a value: `WHERE song = 'order by me'` has no ORDER BY clause.

A literal that is opened and never closed is a parsing error. Nothing is guessed at, because nothing can be: a lone `'` is either a delimiter or a piece of text, and only whoever wrote the query knows which.


## SELECT

The SELECT clause determines the output columns of the query. It contains two types of variables: grouping attrubutes and aggregates. 

Grouping attrubutes are the column names of the datatable that is being queried. It is important to know that ESQL will automatically group these variables (like GROUP BY in SQL), so all rows that contain the same combination of values in the grouping attributes will be in the same row in the output.

<!-- grammar:aggregate-functions -->
Aggregates are what will be calculated for each combination of grouping attributes. An aggregate names one of the aggregate functions supported by ESQL (`sum`, `avg`, `min`, `max`, `count`) and, for every function but `count`, a column that contains numerical data (e.g. `quant` from the `sales` table). `count` is the exception at both ends: it works with a column of any datatype, and it is the one function that can be written with no column at all. Aggregates can be apart of a group defined in the [OVER](#over) clause. ESQL syntax exclusively utilizes dot notation with groups first, then the column name, and the aggregate function last. Therefore, aggregates come in four forms: `count`, `group.count`, `column.function` or `group.column.function`.

If you wanted to write a query with the grouping attributes `cust` and `prod` that computes the maximum value of `quant`, the sum of `quant` for the group `g1`, and the average of `quant` for the group `g2`, you would write:

`SELECT cust, prod, quant.max, g1.quant.sum, g2.quant.avg`

### Counting

`count` answers two different questions, and which one it answers is decided by whether it names a column:

| written | answers |
|---|---|
| `count` | how many rows this group holds |
| `prod.count` | how many distinct products this group holds |
| `g1.count` | how many rows group `g1` holds |
| `g1.prod.count` | how many distinct products group `g1` holds |

A row count names no column because no column bears on it. That is the whole reason the bare form exists: with only `column.count` to write, `SELECT cust, prod.count` had to borrow a column to count rows, and under a clause that groups automatically it reads as "the products, counted" while answering something else. Now the two questions have two spellings, and a column written in an aggregate always bears on the number that comes back.

The other four functions are unchanged and always run over rows, not over distinct values. So `quant.sum` divided by `quant.count` is *not* `quant.avg`, the way it is in SQL: `avg` keeps its own definition, and the identity simply does not hold once `count` means something else.

A blank cell is not a value, so it is skipped by a distinct count and by every other function, while a row count still counts its row. On a column that is blank everywhere, a distinct count has no value at all rather than zero, the same as any aggregate with nothing to compute.

`count` is a reserved name, and the queried data cannot use it for a column. Written on its own the word is the row count wherever a column could go, so a column of that name would be a word with two readings and nothing in the query to pick between them. ESQL refuses such a table outright, names the column and asks you to rename it in the data, rather than preferring a reading and answering.

Only names that can be a whole aggregate are taken this way, which today is `count` alone. `sum` is never an aggregate by itself, so a column may be called `sum` and `sum.sum` is its total.


## OVER

The OVER clause determines the names of the groups that are used to compute aggregates within the conditions set in the [SUCH THAT](#such-that) clause. The groups names are separated by commans. Group names can only include letters, numbers, and `_`, and they are not case sensitive: `OVER G1` can be referenced as `g1` anywhere below. Because they are not case sensitive, two names differing only in case would name the same group and are rejected. It is recommended that group names are short and concise.

A group also cannot be named after a column of the queried data, and that is rejected too. The word to the left of a dot is read as a group or as a column depending on which one it names, so a name that is both makes `sales.count` mean either the group's row count or the distinct count of a column called `sales`. Choosing between those readings would make the same query mean different things over different data, so the name is refused where you pick it instead.

If you want to define two groups with the names `g1` and `g2`, like in the SELECT clause example above, you would write:

`OVER g1, g2`

The following would also be a valid OVER clause:

`OVER my_group_1, 233, group_name`


## WHERE

The WHERE clause determines which rows will be filtered out of the inputted datatable before computing any aggregates. The resulting table will be used to compute any global aggregates.

<!-- grammar:operators WHERE also:==,HAS -->
WHERE clause conditions can include any column in the inputted datatable followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`, `CONTAINS`) and the value that you want to compare to. The comparison value should be the same datatype as the column you are referencing. 

### Which operators apply to which columns

Not every operator applies to every column. Equality works on all four kinds of column, ordering needs values with an order, and `CONTAINS` needs text:

<!-- grammar:operator-dtypes -->

| column | `=` `!=` | `>` `>=` `<` `<=` | `CONTAINS` |
|---|---|---|---|
| number | yes | yes | no |
| date | yes | yes | no |
| text | yes | no | yes |
| boolean | yes | no | no |

An operator used against a column it does not apply to is a parsing error, raised before the value is even read, so `song > 'Dark Star'` is refused rather than answered with an empty table. This is a property of the operator and not of the clause: the same table governs [SUCH THAT](#such-that). [HAVING](#having) has no place in it, because it compares aggregates and every aggregate is numeric.

The value is then read as the column's own kind, and only that kind:

| column | value is written as | examples |
|---|---|---|
| number | a bare number | `quant > 500`, `quant = 12.5` |
| date | a quoted `YYYY-MM-DD` or `YYYY/MM/DD` | `date >= '2020-01-01'` |
| text | a quoted value (see [Text values](#text-values)) | `prod = 'Ham'` |
| boolean | `true` or `false`, unquoted, any case | `credit = true` |

A value written as some other kind is a parsing error, not a comparison that quietly matches nothing: `credit = 1` and `date = 'hello'` are both refused.

A tool that offers completions should read this from `esql.GRAMMAR["operators"]["dtypes"]` rather than copying the table, since the parser enforces the same structure the export is built from.


Conditions can be combined with `AND` and `OR`. The `NOT` operator can also be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`. A boolean column (like `credit` in the `sales` table) can also be a stand alone condition since it will implictly convert to a boolean.

A WHERE condition can also be a [`HAS`](#has) semi-join, which filters on what a row's *group* contains rather than on the row itself.

Below is an example of a valid WHERE clause:

`WHERE NOT (quant >= 500 AND state = 'CT') OR credit`

### CONTAINS

`CONTAINS` keeps rows whose text column contains the given substring anywhere in it, so a filter is not limited to exact equality:

`WHERE prod CONTAINS 'err'`

Three rules apply to it and not to the other operators:

- **It is case insensitive.** `'err'`, `'ERR'` and `'Err'` all match `Cherry`. This is the same behavior as SQL's `LIKE '%err%'`.
- **Both sides must be text.** The column has to be a text column and the value has to be quoted. `quant CONTAINS '5'` is a parsing error, not a match against the digits of a number, and a date column is not text either: `date CONTAINS '2020'` is refused rather than matched against how the date is written. Use a range for that (`date >= '2020-01-01' AND date <= '2020-12-31'`).
- **It is not available in HAVING**, which compares aggregates, and every aggregate is numeric.

It works in [SUCH THAT](#such-that) exactly as it does here, prepended by a group name:

`SELECT venue, g1.quant.sum OVER g1 SUCH THAT g1.prod CONTAINS 'err'`

### HAS

`HAS` keeps rows whose *group* contains a row matching a condition. It is written `<key> HAS <condition>` and reads as "this row's `key` value belongs to some row satisfying `condition`":

`WHERE state HAS prod = 'Ham'`

That keeps every row from every state that ever sold Ham, not just the Ham rows. It is the same thing SQL writes as a subquery, without needing one:

```sql
WHERE state IN (SELECT state FROM sales WHERE prod = 'Ham')
```

This is how a query reaches across two grains of the same table. If a table is one row per song and a "show" is really the derived grain `date`, then `date HAS song = 'Dark Star'` selects every song played at any show that also played Dark Star, without a `shows` table and without a join.

Four rules to know:

- **The condition after `HAS` is a whole condition, not a value.** That is what separates `HAS` from the operators above it. Anything valid in a WHERE condition works there, including [`CONTAINS`](#contains) and another `HAS`.
- **It reads the unfiltered table.** The rest of the WHERE clause does not narrow what the condition after `HAS` can see, because that clause is what `HAS` is helping to filter. So `WHERE state HAS prod = 'Ham' AND prod != 'Ham'` means "everything except Ham, in the states that sold Ham" rather than an empty result.
- **`AND` and `OR` bind looser than `HAS`.** `a HAS b = 1 AND c = 2` reads as `(a HAS b = 1) AND (c = 2)`. Parenthesize to pull a compound condition inside instead: `a HAS (b = 1 AND c = 2)`.
- **It is a row filter, so it belongs only in WHERE.** [SUCH THAT](#such-that) and [HAVING](#having) run after rows are grouped and reject it.

`HAS` has no case sensitivity of its own. It is a quantifier, not a comparison, so the condition inside it behaves exactly as it would on its own: `date HAS song = 'Dark Star'` is case sensitive because `=` is, and `date HAS song CONTAINS 'dark'` is case insensitive because `CONTAINS` is. Matching on the key itself is case sensitive, the same as grouping.


## SUCH THAT
The SUCH THAT clause determines which of the remaining rows will be used to compute aggregates within a group. The SUCH THAT clause should contain a section for each defined group in the [OVER](#over) clause. These sections must be divided by commas, must contain only one group, and must not contain a group that is already defined in another section of the SUCH THAT clause.

<!-- grammar:operators SUCH THAT also:== -->
SUCH THAT clause conditions can include any column in the inputted datatable but every column name must start with the group name of the section combined using dot notation (e.g. `group1.month`). The group and column is followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`, `CONTAINS`) and the value that you want to compare to. The comparison value should be the same datatype as the column you are referencing. [Which operators apply to which columns](#which-operators-apply-to-which-columns) governs here exactly as it does in WHERE.

Conditions can be combined with `AND` and `OR`. The `NOT` operator can also be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`. A boolean column (like `credit` in the `sales` table) can also be a stand alone condition since it will implictly convert to a boolean. A boolean column must still be prepended by a valid group.

[`HAS`](#has) is not valid here. It filters rows before they are grouped, so it belongs in [WHERE](#where).

For example, one section that defines a group to only contain the state 'NJ' or 'NY, assuming group `g1` is defined in the `OVER` clause, would be written as:

`SUCH THAT g1.state = 'NJ' or g1.state = 'NY'`

If there were 4 groups named `q1`, `q2`, `q3`, and `q4`, the following would be a valid SUCH THAT clause:

```
SUCH THAT q1.month = 1 or q1.month = 2 or q1.month = 3,
          q2.month = 4 or q2.month = 5 or q2.month = 6,
          q3.month = 7 or q3.month = 8 or q3.month = 9,
          q4.month = 10 or q4.month = 11 or q4.month = 12
```

### Entry values

Every condition above compares against a fixed value, so it asks the same question of every output row. An **entry value** compares against the output row itself: write a grouping attribute where the value would go, and it stands for whatever that row holds for it.

That is what lets a group reach rows the output row does not contain. Written with an offset, it reaches the group beside it:

```
SELECT cust, month, quant.avg, prev.quant.avg
OVER prev
SUCH THAT prev.cust = cust and prev.month = month - 1
```

Each row shows a customer's average for its month next to that same customer's average for the month before. Group `prev` is scoped to a different month for every row in the result, which no constant can express. This is the difference between an MF query and an **EMF** (Extended Multi-Feature) query in the papers this language is drawn from.

Written without an offset, an entry value reaches every row sharing a value:

```
SELECT cust, month, quant.sum, all_months.quant.sum
OVER all_months
SUCH THAT all_months.cust = cust
```

Each row shows its own month's total beside the customer's total across all months.

Five rules apply:

- **It must be a grouping attribute**, one of the plain columns in [SELECT](#select). Any other column has no single value in a grouped row, so referencing one is a parsing error.
- **The linkage is not implicit.** A section of constants only ever feeds a group from its own rows, so it stays inside the grouping combination without being asked. An entry value does not, which is why `prev.cust = cust` is written out above. Leave it off and group `prev` reads every customer's previous month, not this customer's.
- **An offset needs numbers on both sides.** `month - 1` and `month + 1` work on a numeric column. A text or date attribute can be referenced but not offset.
- **Both sides must be the same kind of value.** A numeric column compares against a numeric attribute, text against text, dates against dates. Mixing them is a parsing error rather than a comparison that quietly matches nothing.
- **Only SUCH THAT takes one.** [WHERE](#where) runs before rows are grouped, so there is no grouped row to read a value from, and [HAVING](#having) compares aggregates against numbers. Both reject it.

A group that finds no rows leaves its aggregates empty for that output row, the same as any other unmatched group: month 1 above has no month 0, so its `prev.quant.avg` comes back missing.

Quoting turns a reference back into text. `g1.prod = 'cust'` looks for the literal string `cust`, not for the row's customer.


## HAVING

The HAVING clause determines which of the grouped rows will be included in the output based on aggregate values.

Aggregates take the same four forms here as in the [SELECT](#select) clause, `count` and `g1.count` included, so `HAVING count > 100` keeps the groups with more than a hundred rows. The HAVING clause is not limited to the aggregates defined in the SELECT clause. The only limitation is that they must be contain an aggregate function (`sum`, `avg`, `min`, `max`, `count`) and a column that contains numerical data (e.g. `quant` from the `sales` table) unless the aggregate function used is `count`. They can also contain a group defined in the `OVER` clause.

<!-- grammar:operators HAVING also:== -->
HAVING clause conditions must include an aggregate followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`) and the value that you want to compare to.

The comparison value must be numeric, as all aggregates are computed numeric values. For that reason [`CONTAINS`](#contains) is the one conditional operator HAVING does not accept, and [`HAS`](#has) is rejected too, since it filters rows rather than groups. 

Conditions can be combined with `AND` and `OR`. The `NOT` operator can be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`.

If you would like the output to only contain rows where the average of `quant` is greater than `3000`, you would write:

`HAVING quant.avg > 3000`

The following is also a valid HAVING clause, assuming the groups `g1` and `g2` are defined in the `OVER` clause:

`HAVING g1.quant.sum < 1000 AND NOT (g2.quant.avg > 500 OR g2.quant.min <= 20)`

## ORDER BY

The ORDER BY clause determines the order of the rows in the outputted table. It takes a comma-separated list of [SELECT](#select) terms to sort by, outermost first. A term is a grouping attribute or an aggregate, and a `-` in front of it sorts that term descending:

```sh
ORDER BY song           -- alphabetically by song
ORDER BY -count         -- most played first
ORDER BY -count, song   -- most played first, ties broken alphabetically
```

Each term carries its own direction, so `ORDER BY -count, song` runs the count down and the song up.

A term must be something the query returns. This is stricter than SQL, where ORDER BY can name a column the query does not select, and grouping is why: a column that is neither a grouping attribute nor inside an aggregate has no single value in an output row to sort by. Naming one is a parsing error that lists the terms available.

Sorting is alphabetical for text and low-to-high for numbers and dates. A row with no value for a term (an aggregate whose [SUCH THAT](#such-that) section matched nothing) sorts last.

### The number shorthand

A single number is shorthand for the first N grouping attributes, in the order the SELECT clause declares them. It is *first N*, not the Nth:

| written | means |
|---|---|
| `ORDER BY 1` | sort by the first grouping attribute |
| `ORDER BY 2` | sort by the first, then the second |
| `ORDER BY -2` | the same two, both descending |
| `ORDER BY 0` | no sort, the same as omitting the clause |

The number can never reach an aggregate, however large it is, because the sort it describes always begins at the first grouping attribute. That is what the term list above is for. If `cust` and `prod` are the grouping attributes, `ORDER BY 2` and `ORDER BY cust, prod` are the same query.
