# # notimailer - Notification content generator.
# All exceptions thrown here will be ValueError exceptions.

#from smtplib import SMTP
import smtplib
import jinja2

# TODO: Support "profiles" for various use cases
# Allow profile to (further) dictate what kinda things (keys) are expected to appear in input data

# Construct notification mailer
class notimailer(object):
  smtphost = None
  def __init__(self, conf, **kwargs):
    if not conf: raise ValueError("No notimailer config");
    if not conf["sysenv"]: raise ValueError("Environment config missing !");
    se = conf["sysenv"]
    notimailer.smtphost = se.get("smtphost")
    if not notimailer.smtphost: raise ValueError("SMTP Host missing !");
    self.tmpl  = conf["tmpl"]
    self.stmpl = conf["subjtmpl"]
    self.smtpfrom = se.get("smtpfrom")
    ####################
    #def connect():
    self.server = smtplib.SMTP()
    self.server.connect(host=notimailer.smtphost, port=25)
    if kwargs.get("debug"): self.server.set_debuglevel(1)
    #helo = self.server.helo(name='Bill') # Returns tuple
    #print("Helo:" + str(helo) + ", in-obj:" + self.server.helo_resp + ".")
    # load templates
    print("Subject Template: " + self.stmpl);
    self.bodytmpl = notimailer.loadtemplate(self.tmpl)
    self.subjtmpl = notimailer.loadtemplate(self.stmpl, iscont=True)
    #print("Templates OK");
    if not self.bodytmpl: raise ValueError("No Body Template");
    if not self.subjtmpl: raise ValueError("No Subject Template");
  # Construct template by loading it from file or using passed value as template string.
  # By passing iscont=True in kwargs, fname parameter is expected to be the template content
  # not a filename.
  @staticmethod
  def loadtemplate(fname, **kwargs):
    tstr = ""
    if kwargs.get('iscont'):
      tstr = fname
    else:
      tpath = kwargs.get("basepath") or "./"
      tstr = open(tpath + fname, "r").read(); # "gerrit_open_notify.j2"
    
    if kwargs.get("debug") > 2: print("Template:" + tstr); exit(0);
    print("Template Content NOW:" + tstr);
    #NOTUSED:template = jinja2.Template(tstr)
    # NOTE: Jinja2 seems to mandate a "\n" in tstr (not a single liner snippet) !
    # OLD Complex "Environemnt" way of creating template
    #env = jinja2.Environment(tstr)
    #template = env.from_string(tstr)
    template = jinja2.Template(tstr)
    if kwargs.get("debug") > 2: print("Env: " + str(env) + ", template:" + str(template) + ".");
    return template

  # Email people related to long pending changes.
  # Params:
  # - changes - Gerrit changes structures with added-on  manager info
  # - accts_idx - Fast lookup index for full user accounts info
  # TODO: Pass pre-prepared templates and email config.
  # kwargs:
  # - debug - Verbose output
  # - noemail - No actual emailing to the people to be notified
  # - adminto - Admin email addresses to send a summarizing (with all messages concatenated) email to
  # - adminsample - Send only single email as "actual sample" to adminlist (Looking exactly like real recipient would have it)
  # - tdictcb - Template dictionary callback
  # Entries in param changes must have keys:
  # - wtid - Work task id label
  # - subject - Work task reabable name / description
  def notify(self, changes, accts_idx, **kwargs):
    if not self.smtpfrom: raise ValueError("No From address for notification");
    #smtpfrom = "ccxswbuild@broadcom.com" # smtpfrom = this.smtpfrom
    emailcfg = {"from": self.smtpfrom, "to": None}
    server = self.server # SMTP() # Server may be passed already here.
    #smtpconn =
    
    ############ Templating ##############
    #template = notimailer.loadtemplate(self.tmpl);
    #if not template: print("No Template");exit(1);
    #exit(0)
    
    i = 0
    collout = "" # Cumulated / Collective output (e.g. to admin)
    doemail = not kwargs.get("noemail")
    adminto = kwargs.get("adminto")
    tdictcb = kwargs.get("tdictcb") or None
    totnote = ""
    subject = ""
    if adminto and (len(adminto) > 0): emailcfg["to"] = adminto

    #print("doemail: " + str(doemail)); exit(1);
    for ch in changes:
      # 
      chid = ch["wtid"]
      #OLD:uid = ch["owner"]["_account_id"] # NEW: "userkey"
      uid = ch["userkey"]
      # u - User. Has full name in "name"
      u = accts_idx.get(str(uid), None)
      if not u: print("No User " +str(uid) + " in index (skip...)."); continue
      if not u["name"]: print("Warning: User " +str(uid) + " has no 'name' for email full name display."); continue
      if kwargs.get("debug") > 1: print(json.dumps(u) + "\n");
      # Template params. Deep clone u to base params on ?
      p = None
      if tdictcb: p = tdictcb(ch, u)
      else: p = { "name": u["name"], "wtid": chid, "subject": ch["subject"], "age_d": ch["age_d"] }
      if not u: print("No user " + str(uid) + " in (accts_idx) Index !"); continue
      if not u.get("email"): print("No user " + str(uid) + " email info in (accts_idx) Index !"); continue
      
      # DONOTUSE: recipients = [ u["email"] ] # Primary
      recipients = [ u["name"] + " <" + u["email"] + ">" ]
      if u.get("manager") and u["manager"].get("email"):
        mgr = u["manager"]
        if not mgr["name"]: print("Warning: User's manager " +str(mgr["username"]) + " has no 'name' for email full name display."); continue
        recipients.append(mgr["name"] + " <" + mgr["email"] + ">") # Add manager (Old/plain: mgr["email"])
      out = self.bodytmpl.render(**p)
      print(str(i) + ") Send Work Task Notif.:" + str(chid) + " To:" + ', '.join(recipients) + ".")
      #print("OUT:" + out);
      collout += out # Add to collective summary (Sent to admin)
      # Note: smtplib wants recipients redundantly in headers (!)
      sstr = self.subjtmpl.render(**p)
      out = "To: " + ", ".join(recipients) + "\nSubject: "+ sstr +"\n\n" + out # Add subject
      if kwargs.get("adminsample"): collout = out; break
      if doemail: server.sendmail(emailcfg["from"], recipients, out)
      else: print(out) # Merely debug
      i += 1
    # Summarizing Admin Email (TODO: Template)
    # SUMMARIZING TEST OUTPUT FOLLOWS.
    if not kwargs.get("adminsample") and emailcfg["to"]:
      totnote = "THESE NOTIFICATIONS ARE TO BE SENT OUT INDIVIDUALLY.\n" + str(i) + " Notifications going out on Work Tasks:\n"
      subject = "To: "+", ".join(emailcfg["to"])+"\nSubject: Work Task notifications ("+str(i)+")\n\n"
    # Note: headers MUST be bundeled to msg (!) with "\n\n" delimiting headers and body
    
    # Admin email
    # .. or to some DL, e.g. (?)
    #emailcfg["to"] = "\"CCXSW-DEVOPS-LIST,PDL\" <ccxsw-devops-list.pdl@broadcom.com>"
    if emailcfg["to"]:
      print("Sending out Summarizing Admin email: "+" ".join(emailcfg["to"])+"...");
      server.sendmail(emailcfg["from"], emailcfg["to"], subject + totnote + collout)
    server.quit()
    return i
