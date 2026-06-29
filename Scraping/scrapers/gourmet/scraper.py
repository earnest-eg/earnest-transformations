import requests
import json
import time
import csv
import math

class GourmetGraphQLScraper:
    def __init__(self):
        self.url = "https://gourmetegypt.com/graphql"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Content-Type': 'application/json'
        }
        self.page_size = 100
        self.products_file = 'gourmet_products_graphql.csv'
        self.json_file = 'gourmet_products_graphql.json'
        self.all_products = []

    def get_query(self, current_page):
        return f"""
        {{
          products(filter: {{}}, pageSize: {self.page_size}, currentPage: {current_page}) {{
            total_count
            items {{
              name
              sku
              url_key
              description {{
                html
              }}
              categories {{
                name
                url_path
              }}
              image {{
                url
              }}
              price_range {{
                minimum_price {{
                  regular_price {{
                    value
                  }}
                  final_price {{
                    value
                  }}
                  discount {{
                    amount_off
                    percent_off
                  }}
                }}
              }}
            }}
          }}
        }}
        """

    def parse_product(self, item):
        if not item:
            return None
            
        price_range = item.get('price_range') or {}
        min_price = price_range.get('minimum_price') or {}
        regular_price_obj = min_price.get('regular_price') or {}
        final_price_obj = min_price.get('final_price') or {}
        discount_obj = min_price.get('discount') or {}
        
        regular_price = regular_price_obj.get('value')
        final_price = final_price_obj.get('value')
        discount_percent = discount_obj.get('percent_off')
        
        current_price = final_price
        old_price = regular_price if regular_price != final_price else None
        discount = f"{discount_percent}%" if discount_percent else None
        
        categories = item.get('categories') or []
        category_name = categories[-1].get('name') if categories else None
        
        desc = item.get('description') or {}
        specs = {'Description': desc.get('html', '').strip()} if desc.get('html') else {}
        
        url_key = item.get('url_key')
        full_url = f"https://gourmetegypt.com/{url_key}" if url_key else None
        
        image_obj = item.get('image') or {}
        img_url = image_obj.get('url')
        
        return {
            'title': item.get('name'),
            'current_price': current_price,
            'old_price': old_price,
            'discount': discount,
            'url': full_url,
            'category': category_name,
            'name': item.get('name'),
            'color': None,
            'Specifications': json.dumps(specs, ensure_ascii=False),
            'img_URL': img_url
        }

    def run(self):
        print("Starting GraphQL Scraper...")
        
        # Get total count first
        query = self.get_query(1)
        response = requests.post(self.url, headers=self.headers, json={'query': query}, timeout=20)
        data = response.json()
        
        total_count = data['data']['products']['total_count']
        total_pages = math.ceil(total_count / self.page_size)
        print(f"Total products: {total_count}. Total pages to fetch: {total_pages}")
        
        with open(self.products_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'current_price', 'old_price', 'discount', 'url', 'category', 'name', 'color', 'Specifications', 'img_URL'])
            writer.writeheader()
            
            for page in range(1, total_pages + 1):
                print(f"Fetching page {page}/{total_pages}...")
                success = False
                for retry in range(5):
                    try:
                        time.sleep(1) # Polite delay
                        q = self.get_query(page)
                        res = requests.post(self.url, headers=self.headers, json={'query': q}, timeout=30)
                        if res.status_code == 200:
                            items = res.json()['data']['products']['items']
                            for item in items:
                                parsed = self.parse_product(item)
                                if parsed:
                                    writer.writerow(parsed)
                                    self.all_products.append(parsed)
                            success = True
                            break
                        else:
                            print(f"Error {res.status_code}. Retrying...")
                    except Exception as e:
                        print(f"Exception: {e}. Retrying...")
                    time.sleep(2 ** retry)
                
                if not success:
                    print(f"Failed to fetch page {page} after 5 retries.")
                    
        # Write JSON export
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(self.all_products, f, ensure_ascii=False, indent=2)
            
        print("GraphQL scraping completed successfully!")

if __name__ == '__main__':
    scraper = GourmetGraphQLScraper()
    scraper.run()
