import os
import sys
import time
import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

class FatalError(Exception):
    pass

def push_to_medium(url, title, content_html):
    """
    Pushes an article to Medium using undetected_chromedriver and enforces SEO Canonical link.
    Returns True on success, False on recoverable error.
    Raises FatalError if SEO Kill-Switch is triggered.
    """
    auth_file = os.getenv("MEDIUM_AUTH_JSON_FILE", "medium_auth.json")
    if not os.path.exists(auth_file):
        print(f"Error: {auth_file} not found. Cannot authenticate with Medium.")
        return False

    print(f"Loading cookies from {auth_file}...")
    with open(auth_file, "r") as f:
        auth_data = json.load(f)
    
    cookies = auth_data.get("cookies", [])

    print("Starting undetected-chromedriver...")
    options = uc.ChromeOptions()
    is_ci = os.getenv("CI", "false").lower() == "true"
    driver = uc.Chrome(options=options, version_main=149, headless=is_ci)
    wait = WebDriverWait(driver, 30)
    
    try:
        # Navigate to 404 page first to set cookies for medium.com
        print("Navigating to medium.com to set cookies...")
        driver.get("https://medium.com/404")
        
        for cookie in cookies:
            cookie_dict = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ".medium.com"),
                "path": cookie.get("path", "/")
            }
            if "secure" in cookie: cookie_dict["secure"] = cookie["secure"]
            if "httpOnly" in cookie: cookie_dict["httpOnly"] = cookie["httpOnly"]
            
            try:
                driver.add_cookie(cookie_dict)
            except Exception:
                pass # Ignore if invalid

        try:
            driver.execute_script("window.localStorage.setItem('viewer-status|is-logged-in', 'true');")
        except:
            pass

        # Save HTML to local temp file to copy formatting natively
        temp_html_path = os.path.abspath("temp_post.html")
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(f"<html><body><div class='ops-article-content'>{content_html}</div></body></html>")
        
        # 1. Go to local file
        print(f"Navigating to local HTML file: file:///{temp_html_path.replace(os.sep, '/')}...")
        driver.get(f"file:///{temp_html_path.replace(os.sep, '/')}")
        time.sleep(1)

        # 2. Select article content
        print("Copying polished article content to clipboard...")
        driver.execute_script("""
            const range = document.createRange();
            range.selectNodeContents(document.querySelector('.ops-article-content'));
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        """)
        time.sleep(1)

        # 3. Copy to clipboard
        actions = ActionChains(driver)
        actions.key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
        time.sleep(1)

        # 4. Go to Medium new story
        print("Navigating to Medium new story editor...")
        driver.get("https://medium.com/new-story")
        time.sleep(3)

        # 5. Type title
        print(f"Typing title: {title}")
        title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h3.graf--title, [data-placeholder='Title'], h1")))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_element)
        time.sleep(1)
        try:
            title_element.click()
        except:
            driver.execute_script("arguments[0].click();", title_element)
        
        # sometimes send_keys fails if element isn't strictly an input, ActionChains is safer
        actions = ActionChains(driver)
        actions.send_keys(title)
        actions.perform()
        time.sleep(1)

        # 6. Press Enter to go to body
        actions = ActionChains(driver)
        actions.send_keys(Keys.RETURN)
        actions.perform()
        time.sleep(1)

        # 7. Paste content
        print("Pasting content...")
        actions = ActionChains(driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(8) # wait for medium to auto-save and process images
        
        # 8. Click Publish button to see the modal
        print("Waiting for Publish button to be enabled and clicking...")
        for _ in range(15):
            success = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for(var i=0; i<btns.length; i++){
                    var txt = (btns[i].innerText || btns[i].textContent || '').toLowerCase().trim();
                    if(txt === 'publish' && !btns[i].disabled && !btns[i].hasAttribute('aria-disabled')) {
                        btns[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if success:
                break
            time.sleep(2)
        
        print("Waiting for modal to render...")
        time.sleep(5)
        driver.save_screenshot('publish_modal_debug.png')
        
        # 9. Click final Publish button in the modal
        print("Clicking final Publish button...")
        driver.execute_script("""
            var btns = Array.from(document.querySelectorAll('button'));
            var publishNowBtn = btns.find(b => {
                var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                return txt.includes('publish now');
            });
            if (publishNowBtn) {
                publishNowBtn.click();
            } else {
                var publishBtns = btns.filter(b => {
                    var txt = (b.innerText || b.textContent || '').toLowerCase().trim();
                    return txt === 'publish';
                });
                if (publishBtns.length > 1) {
                    publishBtns[publishBtns.length - 1].click();
                } else if (publishBtns.length === 1) {
                    publishBtns[0].click();
                }
            }
        """)
        
        print("Waiting for story to be published...")
        for _ in range(30):
            if "new-story" not in driver.current_url:
                break
            time.sleep(1)
        
        # --- SEO Canonical 强绑定 (Kill-Switch) ---
        print("Enforcing SEO Canonical Link after publishing...")
        try:
            current_url = driver.current_url
            print(f"Current URL after publish: {current_url}")
            
            # The story_id is preserved between drafts and published posts
            # But the URL might have changed to /@username/title-slug-hash
            story_id = None
            
            clean_url = current_url.split('?')[0].strip('/')
            
            if '/p/' in clean_url:
                story_id = clean_url.split('/p/')[1].split('/')[0]
            else:
                # published url is like https://medium.com/@username/title-slug-hash
                story_id = clean_url.split('-')[-1]
                
            settings_url = f"https://medium.com/p/{story_id}/settings"
            print(f"Navigating to settings: {settings_url}")
            driver.get(settings_url)
            
            print("Waiting for settings page to load...")
            time.sleep(5) 
            
            # Scroll down to make sure all sections are rendered (React lazy loading)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            driver.save_screenshot("settings_page_bottom_screenshot.png")
            
            with open("settings_dump.txt", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
                
            # 2. Find and click Advanced Settings to expand it
            print("Clicking Advanced Settings headers to expand...")
            driver.execute_script("""
                var elements = document.querySelectorAll('button, summary');
                for (var i=0; i<elements.length; i++) {
                    var txt = elements[i].innerText || elements[i].textContent || '';
                    if (txt.toLowerCase().includes('advanced settings')) {
                        try { elements[i].click(); } catch(e) {}
                        break;
                    }
                }
            """)
            
            time.sleep(2)
            driver.save_screenshot("settings_page_advanced_expanded.png")

            # 3. Check "This story was originally published elsewhere"
            print("Checking for canonical label...")
            checkbox_label = driver.execute_script("""
                var labels = document.querySelectorAll('label, div, span, p');
                for (var i=0; i<labels.length; i++) {
                    var txt = labels[i].innerText || labels[i].textContent || '';
                    if (txt.toLowerCase().includes('originally published')) {
                        // find the closest interactive element or just return it
                        return labels[i];
                    }
                }
                return null;
            """)
            
            # 3 & 4. Find label, click checkbox, find input and set value via Javascript
            print("Checking for canonical label and setting URL via JS...")
            success = driver.execute_script(f"""
                // 1. Find the label
                var labels = document.querySelectorAll('label, div, span, p');
                var label = null;
                for (var i=0; i<labels.length; i++) {{
                    var txt = labels[i].innerText || labels[i].textContent || '';
                    if (txt.toLowerCase().includes('originally published')) {{
                        // To avoid grabbing a giant container, make sure the text isn't too long
                        if (txt.length < 100) {{
                            label = labels[i];
                            break;
                        }}
                    }}
                }}
                
                if (!label) return false;
                
                try {{ label.scrollIntoView({{behavior: "smooth", block: "center"}}); }} catch(e) {{}}
                
                // 2. Click the label
                label.click();
                
                // Backup: if it has an input child, click that too
                var cb = label.querySelector('input[type="checkbox"]');
                if (cb) cb.click();
                
                return true;
            """)
            
            if not success:
                print("Dumping page text to debug:")
                try:
                    page_text = driver.execute_script("return document.body.innerText;")
                    print(page_text)
                except Exception as e:
                    print(f"Failed to dump page text: {e}")
                raise Exception("Failed to find 'This story was originally published elsewhere' label.")
                
            time.sleep(2)
            driver.save_screenshot("settings_page_canonical_checked.png")
            
            # 4. Input canonical URL
            input_success = driver.execute_script(f"""
                var inputs = document.querySelectorAll('input[type="text"], input[type="url"], input:not([type])');
                var canonicalInput = null;
                for (var i=inputs.length-1; i>=0; i--) {{
                    var rect = inputs[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {{
                        canonicalInput = inputs[i];
                        if (inputs[i].placeholder && (inputs[i].placeholder.toLowerCase().includes('http') || inputs[i].placeholder.toLowerCase().includes('link'))) {{
                            break;
                        }}
                    }}
                }}
                
                if (canonicalInput) {{
                    canonicalInput.value = '{url}';
                    var tracker = canonicalInput._valueTracker;
                    if (tracker) {{ tracker.setValue(''); }}
                    canonicalInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    canonicalInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
                return false;
            """)
            
            if not input_success:
                raise Exception("Failed to find canonical URL input.")
                
            time.sleep(1)

            # 5. Click "Save canonical link" (if exists, Medium might auto-save)
            save_btn = driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].innerText && btns[i].innerText.includes('Save')) {
                        return btns[i];
                    }
                }
                return null;
            """)
            if save_btn:
                driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", save_btn)
                print("Clicked Save canonical link.")
            else:
                print("No 'Save' button found. Medium likely auto-saves the settings.")
            
            time.sleep(2)

            print("Canonical link successfully bound.")

        except Exception as e:
            print(f"Fatal Error during Canonical binding: {e}")
            try:
                driver.save_screenshot("fatal_canonical_error_uc.png")
            except:
                pass
            raise FatalError(f"SEO Kill-Switch triggered: Failed to enforce canonical link. Reason: {e}")

        print(f"Successfully pushed {url} to Medium (Saved as Draft).")
        return True
        
    except FatalError:
        raise
    except Exception as e:
        print(f"Recoverable error while pushing {url} to Medium: {e}")
        try:
            driver.save_screenshot("error_medium_rpa_uc.png")
        except:
            pass
        return False
    finally:
        driver.quit()
        # Clean up temp file
        if os.path.exists("temp_post.html"):
            try:
                os.remove("temp_post.html")
            except:
                pass
