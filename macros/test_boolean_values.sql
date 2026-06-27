{% test boolean_values(model, column_name) %}

SELECT
    {{ column_name }}
FROM {{ model }}
WHERE CAST({{ column_name }} AS VARCHAR) NOT IN ('0', '1', 'TRUE', 'FALSE', 'true', 'false')

{% endtest %}
