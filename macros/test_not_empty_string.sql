{% test not_empty_string(model, column_name) %}

SELECT
    {{ column_name }}
FROM {{ model }}
WHERE TRIM({{ column_name }}) = ''
   OR {{ column_name }} IS NULL

{% endtest %}
