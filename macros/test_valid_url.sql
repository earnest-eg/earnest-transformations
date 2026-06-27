{% test valid_url(model, column_name) %}

SELECT
    {{ column_name }}
FROM {{ model }}
WHERE {{ column_name }} IS NOT NULL
  AND {{ column_name }} NOT LIKE 'http://%'
  AND {{ column_name }} NOT LIKE 'https://%'

{% endtest %}
