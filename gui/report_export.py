"""Route frozen reports to the owning workspace's single export slot."""
from storage.observation_export import save_observations


def export_report(owner,path,report,protected,*,label):
    workspace=owner.window()
    handler=getattr(workspace,'save_report_export',None)
    if handler is not None:
        return handler(path,report,protected,label=label)
    save_observations(path,report,protected)
    return True


def export_busy(owner):
    workspace=owner.window()
    if getattr(workspace,'workspace_closing',False) or getattr(workspace,'display_export',None) is not None:
        workspace.statusBar().showMessage('実行中の保存が終了してから操作してください。')
        return True
    return False


def prepare_mob_export(owner,store,sources,names=None):
    """Freeze large model evidence first; defer expensive summaries to the worker."""
    from reconstruction.report_snapshot import freeze_mob_report
    workspace=owner.window()
    if len(store.events)>1000 and hasattr(workspace,'save_prepared_report'):
        return freeze_mob_report(store,sources,names)
    return None


def export_prepared(owner,path,prepared,protected,*,label):
    return owner.window().save_prepared_report(path,prepared,protected,label=label)
