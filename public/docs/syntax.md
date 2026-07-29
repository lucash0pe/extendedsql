
# ExtendedSQL Syntax

This document contains information about writing ESQL queries. I will be providing examples as if I was writing a queries for the 'sales' table. The sales table can be found [here](/public/data/sales.csv) or at `/public/data/sales.csv`.

This document is prose. The token sets it describes — the six keywords, the five aggregate functions, and the comparison operators — are defined once in [`src/esql/parser/util.py`](../../src/esql/parser/util.py) as `KEYWORDS`, `AGGREGATE_FUNCTIONS` and `CONDITIONAL_OPERATORS`, re-exported from `esql`. Read those if you need the authoritative list.

## Table of Contents
- [Structure](#structure)
- [SELECT](#select)
- [OVER](#over)
- [WHERE](#where)
- [SUCH THAT](#such-that)
- [HAVING](#having)
- [ORDER BY](#order-by)


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

The query language has 6 keywords: SELECT, OVER, WHERE, SUCH THAT, HAVING, and ORDER BY. The follpowing sections explore the the syntax and use cases of each keyword. ESQL queries do not contain a FROM clause like in SQL since a datatable must be passed in through the DataFrame accessor or through the API. Queries do not require all of the keywords, but variable projection (in the [SELECT](#select) clause) must be performed for the query to produce an output.

ESQL is not case sensitive, including the keywords. Only string comparison in the WHERE and SUCH THAT clauses are case sensitive. The exception is [`CONTAINS`](#where), which is deliberately case insensitive. 


## SELECT

The SELECT clause determines the output columns of the query. It contains two types of variables: grouping attrubutes and aggregates. 

Grouping attrubutes are the column names of the datatable that is being queried. It is important to know that ESQL will automatically group these variables (like GROUP BY in SQL), so all rows that contain the same combination of values in the grouping attributes will be in the same row in the output.

Aggregates are what will be calculated for each combination of grouping attributes. Aggregates must always contain an aggregate function supported by ESQL (`sum`, `avg`, `min`, `max`, `count`) and a column that contains numerical data (e.g. `quant` from the `sales` table) unless the aggregate function is `count`, which works with columns that contain any datatype.  Aggregates can be apart of a group defined in the [OVER](#over) clause. ESQL syntax exclusively utilizes dot notation with groups first, then the column name, and the aggregate function last. Therefore, aggregates can come in two forms: `column.function` or `group.column.function`.

If you wanted to write a query with the grouping attributes `cust` and `prod` that computes the maximum value of `quant`, the sum of `quant` for the group `g1`, and the average of `quant` for the group `g2`, you would write:

`SELECT cust, prod, quant.max, g1.quant.sum, g2.quant.avg`


## OVER

The OVER clause determines the names of the groups that are used to compute aggregates within the conditions set in the [SUCH THAT](#such-that) clause. The groups names are separated by commans. Group names can only include letters, numbers, and `_`, and they are not case sensitive. It is recommended that group names are short and concise.

If you want to define two groups with the names `g1` and `g2`, like in the SELECT clause example above, you would write:

`OVER g1, g2`

The following would also be a valid OVER clause:

`OVER my_group_1, 233, group_name`


## WHERE

The WHERE clause determines which rows will be filtered out of the inputted datatable before computing any aggregates. The resulting table will be used to compute any global aggregates.

WHERE clause conditions can include any column in the inputted datatable followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`, `CONTAINS`) and the value that you want to compare to. The comparison value should be the same datatype as the column you are referencing. 

Conditions can be combined with `AND` and `OR`. The `NOT` operator can also be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`. A boolean column (like `credit` in the `sales` table) can also be a stand alone condition since it will implictly convert to a boolean.

Below is an example of a valid WHERE clause:

`WHERE NOT (quant >= 500 AND state = 'CT') OR credit`

### CONTAINS

`CONTAINS` keeps rows whose text column contains the given substring anywhere in it, so a filter is not limited to exact equality:

`WHERE prod CONTAINS 'err'`

Three rules apply to it and not to the other operators:

- **It is case insensitive.** `'err'`, `'ERR'` and `'Err'` all match `Cherry`. This is the same behavior as SQL's `LIKE '%err%'`.
- **Both sides must be text.** The column has to be a text column and the value has to be quoted. `quant CONTAINS '5'` is a parsing error, not a match against the digits of a number.
- **It is not available in HAVING**, which compares aggregates, and every aggregate is numeric.

It works in [SUCH THAT](#such-that) exactly as it does here, prepended by a group name:

`SELECT venue, g1.quant.sum OVER g1 SUCH THAT g1.prod CONTAINS 'err'`


## SUCH THAT
The SUCH THAT clause determines which of the remaining rows will be used to compute aggregates within a group. The SUCH THAT clause should contain a section for each defined group in the [OVER](#over) clause. These sections must be divided by commas, must contain only one group, and must not contain a group that is already defined in another section of the SUCH THAT clause.

SUCH THAT clause conditions can include any column in the inputted datatable but every column name must start with the group name of the section combined using dot notation (e.g. `group1.month`). The group and column is followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`, `CONTAINS`) and the value that you want to compare to. The comparison value should be the same datatype as the column you are referencing.

Conditions can be combined with `AND` and `OR`. The `NOT` operator can also be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`. A boolean column (like `credit` in the `sales` table) can also be a stand alone condition since it will implictly convert to a boolean. A boolean column must still be prepended by a valid group.

For example, one section that defines a group to only contain the state 'NJ' or 'NY, assuming group `g1` is defined in the `OVER` clause, would be written as:

`SUCH THAT g1.state = 'NJ' or g1.state = 'NY'`

If there were 4 groups named `q1`, `q2`, `q3`, and `q4`, the following would be a valid SUCH THAT clause:

```
SUCH THAT q1.month = 1 or q1.month = 2 or q1.month = 3,
          q2.month = 4 or q2.month = 5 or q2.month = 6,
          q3.month = 7 or q3.month = 8 or q3.month = 9,
          q4.month = 10 or q4.month = 11 or q4.month = 12
```


## HAVING

The HAVING clause determines which of the grouped rows will be included in the output based on aggregate values.

Like in the [SELECT](#select) clause, aggregates can come in the form `column.function` or `group.column.function`. The HAVING clause is not limited to the aggregates defined in the SELECT clause. The only limitation is that they must be contain an aggregate function (`sum`, `avg`, `min`, `max`, `count`) and a column that contains numerical data (e.g. `quant` from the `sales` table) unless the aggregate function used is `count`. They can also contain a group defined in the `OVER` clause.

HAVING clause conditions must include an aggregate followed by a conditional operator (`>`, `<`, `=`, `>=`, `<=`, `!=`) and the value that you want to compare to. The comparison value must be numeric, as all aggregates are computed numeric values. For that reason [`CONTAINS`](#contains) is the one conditional operator HAVING does not accept. 

Conditions can be combined with `AND` and `OR`. The `NOT` operator can be used for negation. 

Conditions can handle `()` for order of operations, and they interpret `==` as `=`.

If you would like the output to only contain rows where the average of `quant` is greater than `3000`, you would write:

`HAVING quant.avg > 3000`

The following is also a valid HAVING clause, assuming the groups `g1` and `g2` are defined in the `OVER` clause:

`HAVING g1.quant.sum < 1000 AND NOT (g2.quant.avg > 500 OR g2.quant.min <= 20)`

## ORDER BY

The ORDER BY clause determines the order of the rows in the outputted table. It should be a number from 0 up to the amount of grouping attributes in the [SELECT](#select) clause, though `ORDER BY 0` will produce the same result as if you omitted the ORDER BY clause from the query. 

ORDER BY will order rows alphabetically or numerically (lowest to highest), starting with the first grouping attribute defined in the SELECT clause and continuing in the order they were defined. If value is 1, it will sort the rows by the first grouping attribute. If the value is 2, it will sort the first attribute and then sort the second attribute while maintaining the order or the first. This can repeat for each possible grouping attribute. Define attributes in the SELECT clause in the order you want them to be sorted.

If you would like to sort the data in reverse order (Z --> A or highest to lowest), you can mark the ORDER BY value as a negative number. This negative number still cannot be outside the range of the grouping attributes.

If `cust` and `prod` were the grouping attributes in the SELECT clause, the following would be a valid ORDER BY clause:

`ORDER BY 2`

To sort it in the reverse order, you would instead write:

`ORDER BY -2`