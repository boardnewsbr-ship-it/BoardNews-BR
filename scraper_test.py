import sys
sys.path.append('C:/Users/Pichau/Documents/antigravity/splendid-shannon')
import scraper

posts = scraper.scrape_instagram_posts('devirbrasil', 'Devir Brasil')
print('Found', len(posts), 'posts')
for p in posts[:3]:
    print(p['title'], p['link'], p['content'][:30])
